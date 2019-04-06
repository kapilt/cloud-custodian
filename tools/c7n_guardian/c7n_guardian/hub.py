import click
import jsonschema

from c7n_org.cli import init

@click.group()
def cli():
    """SecurityHub Multi-Account Enablement"""



@cli.command()
@click.option('-c', '--config',
              required=True, help="Accounts config file", type=click.Path())
@click.option('--master', help='Master account id or name', required=True)
@click.option('-t', '--tags', multiple=True, default=None)
@click.option('-a', '--accounts', multiple=True, default=None)
@click.option('--debug', help='Run single-threaded', is_flag=True)
def enable(config, master, tags, accounts):

    accounts_config, custodian_config, executor = init(
        config, None, debug, False, None, None, None)
    master_info = get_master_info(account_config, master)
    filter_accounts(accounts_config, tags, accounts, not_accounts=[master_info['name']])

    master = MasterAccount(master_info, {}, session)
    master.enable()
    pending = master.enable_accounts(accounts)

    # Create Invitation in master
    with executor(max_workers=4) as w:
        futures = {}
        for p in pending:
            futures[w.submit(MemberAccount.process, p, master_info)] = p
        for f in as_completed(futures):
            

def expand_regions(regions, partition='aws'):
    if 'all' in regions:
        regions = boto3.Session().get_available_regions('ec2')
    return regions


class MasterAccount(object):

    def __init__(self, account_info, config, session):
        pass

    def enable(self, accounts):
        pass

    def disable(self, accounts):
        pass


class MemberAccount(object):

    def __init__(self, account_info, config, session):
        self.account_info = account_info
        self.config = config
        self.session = session

    def enable(self):
        self.ensure_role()
        self.enable_hub()
        self.accept_invitation()

    def status(self):
        pass

    def ensure_role(self):
        pass

    def enable_hub(self):
        pass


    @classmethod
    def process(account_info, master_info):

        MemberAccount(account_info, 
        
