import logging
import operator

from concurrent.futures import as_completed
import click
from tabulate import tabulate

from c7n.credentials import assumed_session
from c7n.utils import format_event
from c7n_org.cli import init, filter_accounts, CONFIG_SCHEMA, WORKER_COUNT

log = logging.getLogger('c7n-guardian')


# make email required in org schema
CONFIG_SCHEMA['definitions']['account']['properties']['email'] = {'type': 'string'}
CONFIG_SCHEMA['definitions']['account']['required'].append('email')


@click.group()
def cli():
    """Automate Guard Duty Setup."""


@cli.command()
@click.option('-c', '--config', required=True, help="Accounts config file", type=click.Path())
@click.option('-t', '--tags', multiple=True, default=None)
@click.option('-a', '--accounts', multiple=True, default=None)
@click.option('--master', help='Master account id or name')
@click.option('--debug', help='Run single-threaded', is_flag=True)
def report(config, tags, accounts, master, debug):
    """report on guard duty enablement by account"""
    accounts_config, master_info, executor = guardian_init(
        config, debug, master, accounts, tags)

    session = assumed_session(master_info['role'], 'c7n-guardian')
    client = session.client('guardduty')
    detector_id = get_or_create_detector_id(client)

    members = {m['AccountId']: m for m in
               client.list_members(DetectorId=detector_id).get('Members')}

    accounts_report = []
    for a in accounts_config['accounts']:
        ar = dict(a)
        accounts_report.append(ar)
        ar.pop('tags', None)
        ar.pop('role')
        ar.pop('regions', None)
        if a['account_id'] not in members:
            ar['member'] = False
            ar['status'] = None
            ar['invited'] = None
            ar['updated'] = None
            continue
        m = members[a['account_id']]
        ar['status'] = m['RelationshipStatus']
        ar['member'] = True
        ar['joined'] = m['InvitedAt']
        ar['updated'] = m['UpdatedAt']

    accounts_report.sort(key=operator.itemgetter('updated'), reverse=True)
    print(tabulate(accounts_report, headers=('keys')))


@cli.command()
@click.option('-c', '--config', required=True, help="Accounts config file", type=click.Path())
@click.option('-t', '--tags', multiple=True, default=None)
@click.option('-a', '--accounts', multiple=True, default=None)
@click.option('--master', help='Master account id or name')
@click.option('--debug', help='Run single-threaded', is_flag=True)
@click.option('--stop-master', help='Stop monitoring in master', is_flag=True)
@click.option('--suspend-member', help='Suspend in member', is_flag=True)
def suspend(config, tags, accounts, master, debug, stop_master, suspend_member):
    """suspend guard duty in the given accounts."""
    accounts_config, master_info, executor = guardian_init(
        config, debug, master, accounts, tags)
    if (stop_master and suspend_member) or (not stop_master and not suspend_member):
        raise ValueError("One and only of suspend master or suspend member must be specified")

    if stop_master:
        master_session = assumed_session(master_info['role'], 'c7n-guardian')
        master_client = master_session.client('guardduty')
        detector_id = get_or_create_detector_id(master_client)
        unprocessed = master_client.stop_monitoring_members(
            DetectorId=detector_id,
            AccountIds=[a['account_id'] for a in accounts_config['accounts']]
        ).get('UnprocessedAccounts', ())

        if unprocessed:
            log.warning("Following accounts where unprocessed\n %s" % format_event(unprocessed))
        log.info("Stopped monitoring %d accounts in master" % len(accounts_config['accounts']))
        return


@cli.command()
@click.option('-c', '--config', required=True, help="Accounts config file", type=click.Path())
@click.option('-t', '--tags', multiple=True, default=None)
@click.option('-a', '--accounts', multiple=True, default=None)
@click.option('--master', help='Master account id or name')
@click.option('--debug', help='Run single-threaded', is_flag=True)
def disable(config, tags, accounts, master, debug):
    """disable and delete guard duty in the given accounts."""
    accounts_config, master_info, executor = guardian_init(
        config, debug, master, accounts, tags)


@cli.command()
@click.option('-c', '--config', required=True, help="Accounts config file", type=click.Path())
@click.option('--master', help='Master account id or name')
@click.option('-a', '--accounts', multiple=True, default=None)
@click.option('-t', '--tags', multiple=True, default=None)
@click.option('--debug', help='Run single-threaded', is_flag=True)
@click.option('--message', help='Welcome Message for member accounts')
@click.option('--region', default='us-east-1', help='Region to use for api calls')
def enable(config, master, tags, accounts, debug, message, region):
    """enable guard duty on a set of accounts"""
    accounts_config, master_info, executor = guardian_init(
        config, debug, master, accounts, tags)

    master_session = assumed_session(master_info['role'], 'c7n-guardian', region=region)
    master_client = master_session.client('guardduty')
    detector_id = get_or_create_detector_id(master_client)

    extant_members = master_client.list_members(DetectorId=detector_id).get('Members', ())
    extant_ids = {m['AccountId'] for m in extant_members}

    # Find extant members not currently enabled
    suspended_ids = {m['AccountId'] for m in extant_members
                     if m['RelationshipStatus'] == 'Disabled'}
    # Filter by accounts under consideration per config and cli flags
    suspended_ids = {a['account_id'] for a in accounts_config['accounts']
                     if a['account_id'] in suspended_ids}
    if suspended_ids:
        unprocessed = master_client.start_monitoring_members(
            DetectorId=detector_id,
            AccountIds=list(suspended_ids)).get('UnprocessedAccounts')
        if unprocessed:
            log.warning(
                "Unprocessed accounts on re-start monitoring %s" % (format_event(unprocessed)))
        log.info("Restarted monitoring on %d accounts" % (len(suspended_ids)))

    members = [{'AccountId': account['account_id'], 'Email': account['email']}
               for account in accounts_config['accounts']
               if account['account_id'] not in extant_ids]

    if not members:
        if not suspended_ids:
            log.info("All accounts already enabled")
        return

    if (len(members) + len(extant_ids)) > 100:
        raise ValueError(
            "Guard Duty only supports 100 member accounts per master account")

    log.info("Enrolling %d accounts in guard duty" % len(members))

    log.info("Creating member accounts")
    unprocessed = master_client.create_members(
        DetectorId=detector_id, AccountDetails=members).get('UnprocessedAccounts')
    if unprocessed:
        log.warning("Following accounts where unprocessed\n %s" % format_event(unprocessed))

    log.info("Inviting member accounts")
    params = {'AccountIds': [m['AccountId'] for m in members], 'DetectorId': detector_id}
    if message:
        params['Message'] = message
    unprocessed = master_client.invite_members(**params).get('UnprocessedAccounts')
    if unprocessed:
        log.warning("Following accounts where unprocessed\n %s" % format_event(unprocessed))

    log.info("Accepting invitations")
    with executor(max_workers=WORKER_COUNT) as w:
        futures = {}
        for a in accounts_config['accounts']:
            if a == master_info:
                continue
            futures[w.submit(enable_account, a, master_info['account_id'], region)] = a

        for f in as_completed(futures):
            a = futures[f]
            if f.exception():
                log.error("Error processing account:%s error:%s",
                          f.exception())
                continue
            if f.result():
                log.info('Enabled guard duty on account:%s' % account['name'])


def enable_account(account, master_account_id, region):
    member_session = assumed_session(
        account['role'], 'c7n-guardian', region=region)
    member_client = member_session.client('guardduty')
    m_detector_id = get_or_create_detector_id(member_client)
    invitations = [
        i for i in member_client.list_invitations().get('Invitations', [])
        if i['AccountId'] == master_account_id]
    invitations.sort(key=operator.itemgetter('InvitedAt'))
    if not invitations:
        log.warning("No guard duty invitation found for %s id:%s" (account['name']))
        return
    member_client.accept_invitation(
        DetectorId=m_detector_id,
        InvitationId=invitations[-1]['InvitationId'],
        MasterId=master_account_id)
    return True


def get_or_create_detector_id(client):
    detectors = client.list_detectors().get('DetectorIds')
    if detectors:
        return detectors[0]
    else:
        return client.create_detector().get('DetectorId')


def get_master_info(accounts_config, master):
    master_info = None
    for a in accounts_config['accounts']:
        if a['name'] == master:
            master_info = a
            break
        if a['account_id'] == master:
            master_info = a
            break

    if master_info is None:
        raise ValueError("Master account: %s not found in accounts config" % (
            master))
    return master_info


def guardian_init(config, debug, master, accounts, tags):
    accounts_config, custodian_config, executor = init(
        config, None, debug, False, None, None, None, None)
    master_info = get_master_info(accounts_config, master)
    filter_accounts(accounts_config, tags, accounts, not_accounts=[master_info['name']])
    return accounts_config, master_info, executor
