
from zope.interface import Interface
    

class IAccount(Interface):
    """An account in a cloud environment.
    """


class IAccountCollection(Interface):
    """
    """

    def filter(attrs):
        """Return an account collection.
        """


class AccountSource(Interface):
    """Source of accounts
    """

    # ConfigFile
    # Orrganization


    

class AccountFeature(Interface):

    def status(self):
        """
        """

    def enable(self):
        """
        """

    def disable(self):
        """
        """
        
