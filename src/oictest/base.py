#!/usr/bin/env python

__author__ = 'rohe0002'

import time

from bs4 import BeautifulSoup

from oic.oic.message import SCHEMA

from oictest.opfunc import do_request
from oictest.opfunc import Operation
from oictest.check import factory
from oictest.check import ExpectedError

class FatalError(Exception):
    pass

class Trace(object):
    def __init__(self):
        self.trace = []
        self.start = time.time()

    def request(self, msg):
        delta = time.time() - self.start
        self.trace.append("%f --> %s" % (delta, msg))

    def reply(self, msg):
        delta = time.time() - self.start
        self.trace.append("%f <-- %s" % (delta, msg))

    def info(self, msg):
        delta = time.time() - self.start
        self.trace.append("%f %s" % (delta, msg))

    def error(self, msg):
        delta = time.time() - self.start
        self.trace.append("%f [ERROR] %s" % (delta, msg))

    def warning(self, msg):
        delta = time.time() - self.start
        self.trace.append("%f [WARNING] %s" % (delta, msg))

    def __str__(self):
        return "\n". join([t.encode("utf-8") for t in self.trace])

    def clear(self):
        self.trace = []

    def __getitem__(self, item):
        return self.trace[item]

    def next(self):
        for line in self.trace:
            yield line

def flow2sequence(operations, item):
    flow = operations.FLOWS[item]
    return [operations.PHASES[phase] for phase in flow["sequence"]]

def endpoint(client, base):
    for _endp in client._endpoints:
        if getattr(client, _endp) == base:
            return True

    return False

def check_severity(stat):
    if stat["status"] >= 4:
        raise FatalError


def pick_interaction(interactions, _base="", content="", req=None):
    if content:
        _bs = BeautifulSoup(content)
        unic = unicode(content, "utf-8")
    else:
        _bs = None
        unic = u''

    for interaction in interactions:
        _match = 0
        for attr, val in interaction["matches"].items():
            if attr == "url":
                if val == _base:
                    _match += 1
            elif attr == "title":
                if _bs is None:
                    break
                if _bs.title is None:
                    break
                if val in _bs.title.contents:
                    _match += 1
            elif attr == "content":
                if unic and val in unic:
                    _match += 1
            elif attr == "class":
                if req and val == req:
                    _match += 1

        if _match == len(interaction["matches"]):
            return interaction

    raise KeyError("No interaction matched")

ORDER = ["url","response","content"]

def run_sequence(client, sequence, trace, interaction, message_mod,
                 environ=None, tests=None):
    item = []
    response = None
    content = None
    url = ""
    test_output = []
    _keystore = client.keystore

    environ["sequence"] = sequence
    environ["cis"] = []
    environ["trace"] = trace

    try:
        for creq, cresp in sequence:
            environ["request_spec"] = req = creq(message_mod)
            try:
                environ["response_spec"] = resp = cresp()
            except TypeError:
                environ["response_spec"] = resp = None

            if trace:
                trace.info(70*"=")

            if isinstance(req, Operation):
                try:
                    req.update(pick_interaction(interaction,
                                                req=creq.__name__)["args"])
                except KeyError:
                    pass
            else:
                try:
                    req.update(pick_interaction(interaction,
                                                req=req.request)["args"])
                except KeyError:
                    pass
                try:
                    environ["request_args"] = req.request_args
                except KeyError:
                    pass
                try:
                    environ["args"] = req.kw_args
                except KeyError:
                    pass

            try:
                _pretests = req.tests["pre"]
                for test in _pretests:
                    chk = test()
                    stat = chk(environ, test_output)
                    check_severity(stat)
            except KeyError:
                pass


            try:
                part = req(environ, trace, url, response, content)
                environ.update(dict(zip(ORDER, part)))
                (url, response, content) = part

                try:
                    for test in req.tests["post"]:
                        if isinstance(test, tuple):
                            test, kwargs = test
                        else:
                            kwargs = {}
                        chk = test(**kwargs)
                        stat = chk(environ, test_output)
                        check_severity(stat)
                        if isinstance(chk, ExpectedError):
                            url = None
                            break
                except KeyError:
                    pass

            except FatalError:
                raise
            except Exception, err:
                environ["exception"] = err
                chk = factory("exception")()
                chk(environ, test_output)
                raise FatalError()

            if not resp:
                continue

            if url:
                done = False
            else:
                done = True

            while not done:
                while response.status in [302, 301, 303]:
                    try:
                        url = response.url
                    except AttributeError:
                        url = response["location"]

                    # If back to me
                    for_me = False
                    for redirect_uri in client.redirect_uris:
                        if url.startswith(redirect_uri):
                            for_me=True

                    if for_me:
                        done = True
                        break
                    else:
                        part = do_request(client, url, "GET", trace=trace)
                        environ.update(dict(zip(ORDER, part)))
                        (url, response, content) = part

                        check = factory("check-http-response")()
                        stat = check(environ, test_output)
                        check_severity(stat)

                if done:
                    break

                _base = url.split("?")[0]

                try:
                    _spec = pick_interaction(interaction, _base, content)
                except KeyError:
                    if creq.method == "POST":
                        break
                    elif endpoint(client, _base):
                        break
                    else:
                        try:
                            _check = getattr(req, "interaction_check")
                        except AttributeError:
                            _check = None

                        if _check:
                            chk = factory("interaction-check")()
                            chk(environ, test_output)
                            raise FatalError()
                        else:
                            chk = factory("interaction-needed")()
                            chk(environ, test_output)
                            raise FatalError()

                if len(_spec) > 2:
                    trace.info(">> %s <<" % _spec["page-type"])
                _op = Operation(message_mod, _spec["control"])

                try:
                    part = _op(environ, trace, url, response, content)
                    environ.update(dict(zip(ORDER, part)))
                    (url, response, content) = part

                    check = factory("check-http-response")()
                    stat = check(environ, test_output)
                    check_severity(stat)
                except FatalError:
                    raise
                except Exception, err:
                    environ["exception"] = err
                    chk = factory("exception")()
                    chk(environ, test_output)
                    raise FatalError

            info = None
            qresp = None
            if not url:
                environ["response"] = qresp = content
            elif resp.where == "url":
                try:
                    info = response["location"]
                except KeyError:
                    try:
                        _check = getattr(req, "interaction_check", None)
                    except AttributeError:
                        _check = None

                    if _check:
                        chk = factory("interaction-check")()
                        chk(environ, test_output)
                        raise FatalError()
                    else:
                        chk = factory("missing-redirect")()
                        stat = chk(environ, test_output)
                        check_severity(stat)
            else:
                check = factory("check_content_type_header")()
                stat = check(environ, test_output)
                check_severity(stat)
                info = content

            if info:
                if isinstance(resp.response, basestring):
                    schema = SCHEMA[resp.response]
                else:
                    schema = resp.response

                chk = factory("response-parse")()
                environ["response_type"] = schema["name"]
                keys = _keystore.get_keys("verify", owner=None)
                try:
                    qresp = client.parse_response(schema, info, resp.type,
                                                  client.state, key=keys,
                                                  client_id=client.client_id)
                    if trace and qresp:
                        trace.info("[%s]: %s" % (qresp.type(),
                                                 qresp.to_dict()))
                    item.append(qresp)
                    environ["response"] = qresp
                except Exception, err:
                    environ["exception"] = "%s" % err
                    qresp = None
                stat = chk(environ, test_output)
                check_severity(stat)

            if qresp:
                try:
                    for test in resp.tests["post"]:
                        if isinstance(test, tuple):
                            test, kwargs = test
                        else:
                            kwargs = {}
                        chk = test(**kwargs)
                        stat = chk(environ, test_output)
                        check_severity(stat)
                except KeyError:
                    pass

                resp(environ, qresp)

        if tests is not None:
            environ["item"] = item
            for test, args in tests:
                chk = factory(test)(**args)
                check_severity(chk(environ, test_output))

    except FatalError:
        pass
    except Exception, err:
        environ["exception"] = err
        chk = factory("exception")()
        chk(environ, test_output)

    return test_output, "%s" % trace


def run_sequences(client, sequences, trace, interaction, message_mod,
                  verbose=False):
    for sequence, endpoints, fid in sequences:
        # clear cookie cache
        client.grant.clear()
        try:
            client.http.cookiejar.clear()
        except AttributeError:
            pass

        err = run_sequence(client, sequence, trace, interaction, message_mod,
                           verbose)

        if err:
            print "%s - FAIL" % fid
            print
            if not verbose:
                print trace
        else:
            print "%s - OK" % fid

        trace.clear()
