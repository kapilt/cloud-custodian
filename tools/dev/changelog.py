import pygit2
import click

from datetime import datetime, timedelta
from dateutil.tz import tzoffset


def commit_date(commit):
    tzinfo = tzoffset(None, timedelta(minutes=commit.author.offset))
    return datetime.fromtimestamp(float(commit.author.time), tzinfo)


aliases = {
    'c7n': 'core',
    'c7n_mailer': 'tools',
    'mailer': 'tools',
    'utils': 'core',
    'cask': 'tools',
    'test': 'tests',
    'dockerfile': 'tools',
    'ci': 'tests'}

skip = set(('release',))


@click.command()
@click.option('--path', required=True)
@click.option('--output', required=True)
@click.option('--since')
def main(path, output, since):
    repo = pygit2.Repository(path)
    if since:
        since = repo.lookup_reference('refs/tags/%s' % since)
        since = commit_date(since.peel())

    groups = {}
    count = 0
    for commit in repo.walk(
            repo.head.target):

        cdate = commit_date(commit)
        if cdate <= since:
            break
        parts = commit.message.strip().split('-', 1)
        if not len(parts) > 1:
            print("bad commit %s %s" % (cdate, commit.message))
            category = 'other'
        else:
            category = parts[0]
        category = category.strip().lower()
        if '.' in category:
            category = category.split('.', 1)[0]
        if '/' in category:
            category = category.split('/', 1)[0]
        if category in aliases:
            category = aliases[category]

        message = commit.message.strip()
        if '\n' in message:
            message = message.split('\n')[0]

        groups.setdefault(category, []).append(message)
        count += 1

    import pprint
    pprint.pprint(dict([(k, len(groups[k])) for k in groups]))

    with open(output, 'w') as fh:
        for k in sorted(groups):
            if k in skip:
                continue
            print("# %s" % k, file=fh)
            for c in sorted(groups[k]):
                print(" - %s" % c.strip(), file=fh)
            print("\n", file=fh)


if __name__ == '__main__':
    main()
