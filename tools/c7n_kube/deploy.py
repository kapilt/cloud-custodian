
from c7n_gcp.client import Session
from c7n_gcp.mu import (
    custodian_archive, HTTPEvent, CloudFunction, CloudFunctionManager)


def main():

    archive = custodian_archive()
    archive.add_contents('main.py', open('c7n_kube/admctrl.py').read())
    archive.close()

    func = CloudFunction({
        'name': 'c7n-k8s-ctrl',
        'memory-size': 512,
        'timeout': '60s',
        'events': [HTTPEvent(None, {})],
        'labels': {
            'env': 'dev'}},
        archive)

    mgr = CloudFunctionManager(Session)
    mgr.publish(func)


if __name__ == '__main__':
    main()

