import click
from collections import Counter
import boto3
import logging
import gzip
import time
import pprint
import os
import sqlite3

from datetime import timedelta
from dateutil.parser import parse as date_parse
from dateutil.tz import tzutc
from dateutil import zoneinfo
from concurrent.futures import ProcessPoolExecutor, as_completed
from flowrecord import FlowRecord


log = logging.getLogger('traffic')


def eni_download_keys(client, bucket, prefix, start, end, eni, store_dir):
    t = time.time()

    # 30m aggregation delay
    #if end:
    #    end_barrier = end + timedelta(seconds=30*60)
    #else:
    #    end_barrier = None
    log_size = count = skip = 0

    eni_path = os.path.join(store_dir, '%s-all' % eni)
    if not os.path.exists(eni_path):
        os.makedirs(eni_path)

    results = client.list_objects_v2(
        Bucket=bucket,
        Prefix="%s/%s" % (
            prefix.rstrip('/'),
            "%s-all" % eni))
    truncated = results['IsTruncated']

    for k in results.get('Contents', ()):
        #if end_barrier and k['LastModified'] > end_barrier:
        #    skip += 1
        #    continue
        #if k['LastModified'] < start:
        #    skip += 1
        #    continue
        dl_key = os.path.join(store_dir, '%s-all' % eni, k['Key'].rsplit('/', 1)[-1])
        log_size += k['Size']
        if os.path.exists(dl_key) and os.path.getsize(dl_key) == k['Size']:
            count += 1
            yield dl_key
            continue
        client.download_file(bucket, k['Key'], dl_key)
        yield dl_key
        count += 1

    log.info("eni:%s logs-skip:%d logs-consumed:%d truncated:%s size:%d" % (
        eni, skip, count, truncated, log_size))


def eni_log_analyze(me, ips, files, inbound=True, outbound=True,
                    start=None, end=None, reject=None, target_ips=None, ports=()):
    #in_packets = Counter()
    in_bytes = Counter()
    in_ports = Counter()
    #out_packets = Counter()
    out_bytes = Counter()
    out_ports = Counter()

    intra_bytes = Counter()
    record_count = 0
    record_bytes = 0

    if start:
        u_start = time.mktime(start.timetuple())
    if end:
        u_end = time.mktime(end.timetuple())

    for f in files:
        with gzip.open(f) as fh:
            line = fh.readline()
            record = FlowRecord(line)

            # record windows typically either 60s or 5m
            #print('record window %0.2f' % (record.end - record.start))
            if start and record.start < u_start:
                #print 'start', record.start, u_start, start, record.start_date
                continue

            # we might lose a few records if we just record.end < u_end
            if end and record.end > u_end:
                #print 'end', record.end, u_end, end, record.end_date
                continue

            record_count += 1
            record_bytes += record.bytes

            if ports and (record.srcport not in ports and record.dstport not in ports):
                continue
            if reject is not None:
                if reject and record.action != 'REJECT':
                    continue
                if reject is False and record.action != 'ACCEPT':
                    continue

            if target_ips:
                if not (record.dstaddr in target_ips or
                            record.srcaddr in target_ips):
                    continue
            if record.dstaddr in ips and record.srcaddr in ips:
                intra_bytes[record.srcaddr] += record.bytes

            if inbound and record.dstaddr in ips:
                #in_packets[record.srcaddr] += record.packets
                in_bytes[record.srcaddr] += record.bytes
                if record.srcaddr not in ips:
                    in_ports[record.srcport] += record.bytes
            elif outbound and record.srcaddr in ips:
                #out_packets[record.dstaddr] += record.packets
                out_bytes[record.dstaddr] += record.bytes
                out_ports[record.dstport] += record.bytes
            else:
                import pdb; pdb.set_trace()
    log.info(
        "eni:%s records:%d inbytes:%d outbytes:%d bytes:%d intra:%d",
        me,
        record_count,
        sum(in_bytes.values()),
        sum(out_bytes.values()),
        record_bytes,
        sum(intra_bytes.values())
        )

    return in_bytes, out_bytes, in_ports, out_ports


def resolve_ip_address(counter, ipdb, cmdb, start, end):
    if not ipdb:
        return counter
    if cmdb:
        cmdb = sqlite3.connect(cmdb)
        cmdb_cursor = cmdb.cursor()

    with sqlite3.connect(ipdb) as conn:
        cursor = conn.cursor()

        lookup_data = {}
        for k in counter.keys():
            cursor.execute(
            '''select * from enis
                where ip_address = ?
                  and start < ?
                  and (end > ? or end is null)''',
                (k, end.strftime('%Y-%m-%dT%H:%M'),
                       start.strftime('%Y-%m-%dT%H:%M')))

            info = list(cursor)
            if info:
                info = info.pop()
            if not info:
                continue
            lookup_data[info[1]] = info

        log.info("Resolved %d of %d ips", len(lookup_data), len(counter.keys()))
        for k in list(counter):
            i = lookup_data.get(k)
            if i is None:
                continue
            if i[3] == 'ec2':
                cmdb_cursor.execute('select * from ec2 where instance_id = ?',
                                        (i[4],))
                i = cmdb_cursor.fetchone()
                v = counter.pop(k)
                counter['%s %s' % (k, " ".join(i[:-1]))] = v
                continue
            v = counter.pop(k)
            counter['%s' % (" ".join(i[:-1]))] = v
    return counter


@click.command()
@click.option('--account-id', required=True)
@click.option('--bucket', required=True)
@click.option('--prefix', required=True, default="")
@click.option('--enis', multiple=True)
@click.option('--ips', multiple=True)
@click.option('--start', required=True)
@click.option('--end')
@click.option('-p', '--ports', multiple=True)
@click.option('--store-dir', required=True)
@click.option('--ipdb')
@click.option('--cmdb')
@click.option('--reject/--no-reject', default=None)
@click.option('-t', '--targets', multiple=True, default=None)
@click.option('--tz')
def main(account_id, bucket, prefix,
             enis, ips, start, end, store_dir,
             ipdb=None, cmdb=None, reject=None, targets=None,
             ports=None, tz=None):

    logging.basicConfig(level=logging.INFO)
    logging.getLogger('botocore').setLevel(logging.WARNING)
    ports = map(int, ports)

    mytz = tz and zoneinfo.gettz(tz) or tzutc()
    start = date_parse(start).replace(tzinfo=mytz)
    if end:
        end = date_parse(end).replace(tzinfo=mytz)
    if tz:
        start = start.astimezone(tzutc())
        if end:
            end = end.astimezone(tzutc())

    client = boto3.client('s3')
    log_prefix = "%s/%s/flow-log/%s/%s" % (
        prefix.rstrip('/'),
        account_id,
        start.strftime('%Y/%m/%d'),
        "00000000-0000-0000-0000-000000000000")

    agg_in_traffic = Counter()
    agg_out_traffic = Counter()
    agg_inport_traffic = Counter()
    agg_outport_traffic = Counter()

    for eni, ip in zip(enis, ips):
        in_traffic, out_traffic, inport_traffic, outport_traffic = eni_log_analyze(
            (eni, ip),
            ips,
            eni_download_keys(
                client, bucket, log_prefix, start, end, eni, store_dir),
            start=start,
            end=end,
            reject=reject,
            target_ips=targets,
            ports=ports)
        agg_in_traffic.update(in_traffic)
        agg_out_traffic.update(out_traffic)
        agg_inport_traffic.update(inport_traffic)
        agg_outport_traffic.update(outport_traffic)

    print("Inbound 20 Most Commmon")
    pprint.pprint(
        resolve_ip_address(agg_in_traffic, ipdb, cmdb, start, end).most_common(20))
    print("Outbound 20 Most Common")
    pprint.pprint(
        resolve_ip_address(agg_out_traffic, ipdb, cmdb, start, end).most_common(20))

    #pprint.pprint(agg_inport_traffic.most_common(20))
    #pprint.pprint(agg_outport_traffic.most_common(20))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        import pdb, traceback, sys
        traceback.print_exc()
        pdb.post_mortem(sys.exc_info()[-1])
