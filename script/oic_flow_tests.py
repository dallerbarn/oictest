#!/usr/bin/env python
import os
import json
import time
import argparse
from subprocess import Popen
from subprocess import PIPE

from oic.utils.keyio import KeyJar
from oic.utils.keyio import key_export
from oictest.graph import Node, flatten
from oictest.graph import sort_flows_into_graph
from rrtest.check import STATUSCODE
from oictest import start_key_server

__author__ = 'rohe0002'

OICC = "oicc.py"

LEVEL = {
    "INFORMATION": 'I',
    "OK": "+",
    "WARNING": "?",
    "ERROR": "!",
    "CRITICAL": "X",
    "INTERACTION": "o"
}


def test(node, who, host, csv=False):
    global OICC

    #print ">> %s" % node.name

    p1 = Popen(["./%s.py" % who], stdout=PIPE)
    cmd2 = [OICC, "-e", "-J", "-", "-H", host, node.name]

    p2 = Popen(cmd2, stdin=p1.stdout, stdout=PIPE, stderr=PIPE)
    p1.stdout.close()
    (p_out, p_err) = p2.communicate()

    reason = ""
    if p_out:
        try:
            output = json.loads(p_out)
        except ValueError:
            print 40 * "=" + "\n" + "failed on '%s'" % node.name + "\n" + \
                p_out + "\n" + 40 * "="
            raise
        node.trace = output
        if output["status"] > 1:
            for test in output["tests"]:
                if test["status"] > 1:
                    try:
                        reason = test["message"]
                    except KeyError:
                        print test
            node.err = p_err
        #print output["status"]
        _sc = STATUSCODE[output["status"]]
    else:
        _sc = STATUSCODE[1]
        node.err = p_err

    node.state = _sc
    sign = LEVEL[_sc]
    if reason:
        if csv:
            print "%s, %s (%s)" % (node.name, _sc, reason)
        else:
            print "%s (%s)%s - %s (%s)" % (sign, node.name, node.desc, _sc, reason)
    else:
        if csv:
            print "%s, %s" % (node.name,_sc)
        else:
            print "%s (%s)%s - %s" % (sign, node.name, node.desc, _sc)


def recursively_test(node, who, host, csv=False):
    for parent in node.parent:
        if parent.state == STATUSCODE[0]:  # untested, don't go further
            print "SKIP %s Parent untested: %s" % (node.name, parent.name)
            return

    test(node, who, host, csv)

    #print "node.state: %s" % node.state

    if node.state in STATUSCODE[0:3]:
        test_all(node.children, who, host, csv)


def test_all(graph, who, host, csv=False):
    skeys = graph.keys()
    skeys.sort()
    for key in skeys:
        recursively_test(graph[key], who, host, csv)

from oictest import KEY_EXPORT_ARGS


def run_key_server(server_url, host, script_path="", wdir=""):
    kj = KeyJar()
    _ = key_export(server_url % host, keyjar=kj, **KEY_EXPORT_ARGS)
    return start_key_server(server_url % host, wdir, script_path)

if __name__ == "__main__":
    from oictest.oic_operations import FLOWS

    _parser = argparse.ArgumentParser()
    _parser.add_argument('-H', dest='host', default="example.org")
    _parser.add_argument('-g', dest='group')
    _parser.add_argument('-e', dest='extkeysrv', action='store_true')
    _parser.add_argument('-c', dest='csv', action='store_true')
    _parser.add_argument('-l', dest='list', action='store_true')
    _parser.add_argument('-E', dest='export_path', default="")
    _parser.add_argument(
        '-S', dest="script_path",
        help="Path to the script running the static web server")
    _parser.add_argument('server', nargs=1)
    args = _parser.parse_args()

    args.server = args.server[0].strip("'")
    args.server = args.server.strip('"')

    p1 = Popen(["./%s.py" % args.server], stdout=PIPE)
    _cnf = json.loads(p1.stdout.read())

    if args.extkeysrv:
        _pop = None
    elif "key_export" in _cnf["features"] and _cnf["features"]["key_export"]:
        if args.script_path:
            _pop = run_key_server(_cnf["client"]["key_export_url"], args.host,
                                  script_path=args.script_path,
                                  wdir=args.export_path)
        else:
            _pop = run_key_server(_cnf["client"]["key_export_url"], args.host,
                                  wdir=args.export_path)
        time.sleep(1)
    else:
        _pop = None

    if args.list:
        keys = FLOWS.keys()
        keys.sort()
        for key in keys:
            node = Node(name=key, desc=FLOWS[key])
            test(node, args.server, args.host, args.csv)
    else:
        flow_graph = sort_flows_into_graph(FLOWS, args.group)
        _l = flatten(flow_graph)
        test_all(flow_graph, args.server, args.host, args.csv)

    if _pop:
        _pop.kill()

    os.wait()