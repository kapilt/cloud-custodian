import logging
import operator

from botocore.exceptions import ClientError
from concurrent.futures import as_completed
import click

from c7n.credentials import assumed_session
from c7n.utils import format_event
from c7n_org.cli import init, CONFIG_SCHEMA, WORKER_COUNT

log = logging.getLogger('c7n-guardian')


# make email required in org schema
CONFIG_SCHEMA['definitions']['accounts']['properties']['email'] = {'type': 'string'}
CONFIG_SCHEMA['definitions']['accounts']['required'].append('email')


@click.group()
def cli():
    """Automate Guard Duty Setup."""


@cli.command()
def check():
    pass


@cli.command()
@click.option('-c', '--config', required=True, help="Accounts config file", type=click.Path())
@click.option('--master', help='Master account id or name')
@click.option('-a', '--accounts', multiple=True, default=None)
@click.option('--tags', help='Target account tag filter')
@click.option('--debug', help='Run single-threaded')
@click.option('--message', help='Welcome Message for member accounts')
@click.option('--region', default='us-east-1', help='Region to use for api calls')
def enable(config, master, tags, accounts, debug, welcome_message, region):
    accounts_config, custodian_config, executor = init(
        config, None, debug, False, accounts, tags, None, None)

    master_info = get_master_info(accounts_config, master)

    master_session = assumed_session(master_info['role'], 'c7n-guardian', region=region)
    master_client = master_session.client('guardduty')

    detector_id = get_or_create_detector_id(master_client)
    members = [{'AccountId': account['account_id'], 'Email': account['email']}
               for account in accounts_config['accounts'] if account != master_info]

    if len(members) > 100:
        raise ValueError(
            "Guard Duty only supports 100 member accounts per master account")

    log.info("Creating member accounts")
    unprocessed = master_client.create_members(
        DetectorId=detector_id, AccountDetails=members)
    if unprocessed:
        log.warning("Fllowing accounts where unprocessed\n %s" % format_event(unprocessed))

    log.info("Inviting member accounts")
    params = {'AccountIds': [m['AccountId'] for m in members], 'DetectorId': detector_id}
    if welcome_message:
        params['Message'] = welcome_message
    unprocessed = master_client.invite_members(**params).get('unprocessedAccounts')
    if unprocessed:
        log.warning("Following accounts where unprocessed\n %s" % format_event(unprocessed))
                
    log.info("Accepting invitations")
    with executor(max_workers=WORKER_COUNT) as w:
        futures = {}
        for a in accounts_config['accounts']:
            futures[w.submit(enable_account, a)] = a

        for f in as_completed(futures):
            a = futures[w]
            if f.exception():
                log.error("Error processing account:%s error:%s",
                          f.exception())
                continue
            if f.result():
                log.info('Enabled guard duty on account:%s' % account['name'])


def enable_account(account, region, master_account_id):
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
    


    
