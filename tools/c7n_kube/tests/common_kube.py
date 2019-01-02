import os

from vcr_unittest import VCRTestCase
from c7n.testing import TestUtils
from c7n.resources import load_resources


load_resources()


class KubeTest(VCRTestCase, TestUtils):

    def _get_vcr_kwargs(self):
        return super(VCRTestCase, self)._get_vcr_kwargs(
            filter_headers=['authorization'],
            before_record_request=self.request_callback)

    def request_callback(self, request):
        return request

    def _get_vcr(self, **kwargs):
        myvcr = super(VCRTestCase, self)._get_vcr(**kwargs)
        myvcr.register_matcher('kubematcher', self.kube_matcher)
        myvcr.match_on = ['kubematcher']
        return myvcr

    def kube_matcher(self, r1, r2):
        return True

    def _get_cassette_library_dir(self):
        return os.path.join(
            os.path.dirname(__file__),
            'data', 'flights')
    

    

        
