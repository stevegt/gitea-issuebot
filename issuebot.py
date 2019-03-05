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

irr_template = """{notes}

irr {cost} {cost_term} {benefit} {benefit_term}

issuebot report: #{report_num}

| var | val |
| --- | --- |
| rate: | {rate:5.2f} |
| cost: | {cost:5.2f} |
| cost_term: | {cost_term} |
| benefit: | {benefit:5.2f} |
| benefit_term: | {benefit_term} |
| cost_pv: | {cost_pv:5.2f} |
| benefit_pv: | {benefit_pv:5.2f} |
| npv: | {npv:5.2f} |
| irr: | {value:5.2f} |
| label: | {label} |

irrend
"""

def cmp(a, b):
    return (a > b) - (a < b)

class Object(object):
    pass

class IRR(object):

    def __init__(self, rate, cost, cost_term, benefit, benefit_term, report_num, notes):
        self.rate = rate
        self.cost = cost
        self.cost_term = cost_term
        self.benefit = benefit
        self.benefit_term = benefit_term
        self.report_num = report_num
        self.notes = notes

        self.cost_pv = cost / (1+rate)**(cost_term/365.0)
        self.benefit_pv = benefit / (1+rate)**(benefit_term/365.0)
        self.npv = self.benefit_pv - self.cost_pv
        self.value = (cost/benefit)**(-1/(benefit_term/365 - cost_term/365)) - 1
        self.label = "irr" + str(int(self.value*100))

    def __str__(self):
        body = irr_template.format(**(self.__dict__))
        return body

    @classmethod
    def match(cls, rate, txt, report_num):
        irr = None
        # irr cost term benefit term
        m = re.match(
            '(.*?)\s*^irr\s+([\d\.]+)\s+([\d\.]+)\s+([\d\.]+)\s+([\d\.]+)\s*(|.*\nirrend)\s*$', 
                txt, re.DOTALL | re.MULTILINE)
        if m:
            notes = m.group(1)
            cost, cost_term, benefit, benefit_term = map(float, m.groups()[1:5])
            irr = cls(rate, cost, cost_term, benefit, benefit_term,
                    report_num, notes)
        return irr

class ReportNode(object):

    def __init__(self, issue):
        self.issue = issue
        self.irr = Object()
        self.irr.value = -1

class Report(object):

    def __init__(self):
        self.db = {}
        self.issue = None

    def __str__(self):
        irrs = '### Issues sorted by IRR:\n\n| irr | issue | title |\n' \
                '| --- | --- | --- |\n'
        missing = '### Issues missing IRR inputs:\n\n| irr | issue | title |\n' \
                '| --- | --- | --- |\n'
        for node in self.dump():
            line = "| {:5.2f} | #{} | {} |\n".format(
                    node.irr.value, node.issue['number'], node.issue['title'])
            if node.irr.value != -1:
                irrs += line
            else:
                missing += line
        out = "{}\n\n{}\n".format(irrs, missing)
        return out

    def add_issue(self, issue):
        node = ReportNode(issue)
        self.db[issue['number']] = node

    def set_irr(self, issue, irr):
        self.db[issue['number']].irr = irr

    def sort_irr(self):
        def get_irr_value(issue_num):
            node =  self.db[issue_num]
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
        # print(self.schema)

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

    # get all open issues 
    page = 1
    while True:
        res = gitea.action('issue', 'issueListIssues', 
                owner=owner, repo=repo, state='open', page=page)
        if not res:
            break
        for issue in res:
            if issue['title'] == 'issuebot report':
                report.issue = issue
                continue
            report.add_issue(issue)
            '''
            # get recently updated
            updated_at = parser.parse(issue['updated_at'])
            if updated_at > start_date:
                recent_issues.append(issue)
            '''
        page += 1
    
    # create report issue if needed
    if not report.issue:
        # create empty issue
        print("creating empty issue titled 'issuebot report'")
        report.issue = gitea.action('issue', 'issueCreateIssue', 
                            owner=owner, repo=repo, title='issuebot report')

    # scan comments for irr inputs
    for issue in report.dump_issues():
        # print(issue)
        res = gitea.action('issue', 'issueGetComments', 
                           owner=owner, repo=repo, index=issue['number'])
        for comment in res:
            irr = IRR.match(rate, comment['body'], report.issue['number'])
            if irr:
                report.set_irr(issue, irr)
                res = gitea.action('issue', 'issueEditComment', 
                    owner=owner, repo=repo, id=comment['id'], body=str(irr))
                assert(res)
            
    # generate report
    body = str(report)
    res = gitea.action('issue', 'issueEditIssue', 
                owner=owner, repo=repo, index=report.issue['number'],
                body=body)


if __name__ == "__main__":
    main()
