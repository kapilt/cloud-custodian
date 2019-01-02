
from .common_kube import KubeTest


class NamespaceTest(KubeTest):

    def test_ns_query(self):
        p = self.load_policy({
            'name': 'all-namespaces',
            'resource': 'k8s.namespace'})
        resources = p.run()
        self.assertEqual(len(resources), 3)
        self.assertEqual(
            sorted([r['metadata']['name'] for r in resources]),
            ['default', 'kube-public', 'kube-system'])
            
    
