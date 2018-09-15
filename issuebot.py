#!/usr/bin/env python

import datetime
from dateutil import parser
import json
import pytz
import os
import re
import sys

import coreapi
from openapi_codec import OpenAPICodec
from coreapi.codecs import JSONCodec
from coreapi import Client

irr_template = """irr {cost} {cost_term} {benefit} {benefit_term}

rate: {rate}
cost: {cost}
cost_term: {cost_term}
benefit: {benefit}
benefit_term: {benefit_term}
cost_pv: {cost_pv}
benefit_pv: {benefit_pv}
npv: {npv}
irr: {irr}
label: {label}

irrend
"""

def cmp(a, b):
    return (a > b) - (a < b)

class Object(object):
    pass

class IRR(object):

    def __init__(self, rate, cost, cost_term, benefit, benefit_term):
        self.rate = rate
        self.cost = cost
        self.cost_term = cost_term
        self.benefit = benefit
        self.benefit_term = benefit_term

        self.cost_pv = cost / (1+rate)**(cost_term/365.0)
        self.benefit_pv = benefit / (1+rate)**(benefit_term/365.0)
        self.npv = self.benefit_pv - self.cost_pv
        self.value = (cost/benefit)**(-1/(benefit_term/365 - cost_term/365)) - 1
        self.label = "irr" + str(int(self.value*100))

    def __str__(self):
        body = irr_template.format(**(self.__dict__))
        return body

    @classmethod
    def match(cls, rate, txt):
        irr = None
        # irr cost term benefit term
        m = re.match(
                '^irr\s+([\d\.]+)\s+([\d\.]+)\s+([\d\.]+)\s+([\d\.]+)\s*(|.*\nirrend)\s*$', 
                txt, re.DOTALL)
        if m:
            cost, cost_term, benefit, benefit_term = map(float, m.groups()[:4])
            irr = cls(rate, cost, cost_term, benefit, benefit_term)
        return irr

class ReportNode(object):

    def __init__(self, issue):
        self.issue = issue
        self.irr = Object()
        self.irr.value = -1

class Report(object):

    def __init__(self):
        self.db = {}

    def __str__(self):
        irrs = '### Issues sorted by IRR:\n\n'
        missing = '### Issues missing IRR inputs:\n\n'
        for node in self.dump():
            line = "- {:5.2f} #{}\n".format(node.irr.value, node.issue['id'])
            if node.irr.value != -1:
                irrs += line
            else:
                missing += line
        out = irrs + '\n\n' + missing
        return out

    def add_issue(self, issue):
        node = ReportNode(issue)
        self.db[issue['id']] = node

    def set_irr(self, issue, irr):
        self.db[issue['id']].irr = irr

    def sort_irr(self):
        def get_irr_value(issue_id):
            node =  self.db[issue_id]
            return node.irr.value
        return sorted(self.db.keys(), key=get_irr_value, reverse=True)

    def dump(self):
        return [ self.db[x] for x in self.sort_irr() ]

    def dump_issues(self):
        return [ x.issue for x in self.dump() ]

class Gitea(object):

    def __init__(self, url, token):
        auth = coreapi.auth.TokenAuthentication(token, scheme='token', domain='*')
        decoders = [OpenAPICodec(), JSONCodec()]
        self.client = Client(decoders=decoders, auth=auth)
        self.schema = self.client.get(url, format='openapi')
        # print(schema)

    def action(self, tag, op, **kwargs):
        return self.client.action(self.schema, [tag, op], params=kwargs)

def main():
    confn = sys.argv[1]
    rate = float(sys.argv[2])
    # days = float(sys.argv[3])

    confh = open(confn, 'r')
    conf = json.load(confh)

    now = datetime.datetime.utcnow().replace(tzinfo=pytz.UTC)
    # start_date = now - datetime.timedelta(days=days)

    owner = conf['owner']
    repo = conf['repo']

    gitea = Gitea(conf['url'], conf['token'])

    report = Report()
    report_issue = None

    # get all open issues 
    page = 1
    while True:
        res = gitea.action('issue', 'issueListIssues', 
                owner=owner, repo=repo, state='open', page=page)
        if not res:
            break
        for issue in res:
            if issue['title'] == 'issuebot report':
                report_issue = issue
                continue
            report.add_issue(issue)
            '''
            # get recently updated
            updated_at = parser.parse(issue['updated_at'])
            if updated_at > start_date:
                recent_issues.append(issue)
            '''
        page += 1
    
    # scan comments for irr inputs
    for issue in report.dump_issues():
        res = gitea.action('issue', 'issueGetComments', 
                owner=owner, repo=repo, index=issue['id'])
        for comment in res:
            irr = IRR.match(rate, comment['body'])
            if irr:
                report.set_irr(issue, irr)
            
    # create report issue if needed
    if not report_issue:
        # create empty issue
        print("creating empty issue titled 'issuebot report'")
        report_issue = gitea.action('issue', 'issueCreateIssue', 
                            owner=owner, repo=repo, title='issuebot report')

    res = gitea.action('issue', 'issueEditIssue', 
                owner=owner, repo=repo, index=report_issue['id'],
                body='new body2')

    # get report comment 
    res = gitea.action('issue', 'issueGetComments', 
                owner=owner, repo=repo, index=report_issue['id'])
    if res:
        report_comment = res[0]
    else:
        # create comment
        res = gitea.action('issue', 'issueCreateComment', 
                    owner=owner, repo=repo, index=report_issue['id'],
                    body='placeholder')
        report_comment = res

    print('XXX')
    print(report_issue)
    print('YYY')
    print(report_comment)
    print('ZZZ')

    sys.exit(1)

    body = str(report)
    print(body)
    params = dict(owner=owner, repo=repo, index=issue['id'], body=body)
    res = client.action(schema, ['issue', 'issueEditIssue'], params=params)
    print(res)

    sys.exit(1)



    # XXX this stanza is from json2coreapi.py, needs to go away
    txt = sys.stdin.read()
    obj = json.loads(txt)
    tag = obj['tag']
    op = obj['op']
    if 'params' in obj:
        params = obj['params']
    else:
        params = None

    # XXX this stays
    res = client.action(schema, [tag, op], params=params)

    # XXX this goes
    print(json.dumps(res))
    

if __name__ == "__main__":
    main()
