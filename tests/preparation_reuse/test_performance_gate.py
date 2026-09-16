import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from qualify_preparation_performance import SDK, evaluate


class PerformanceGateTests(unittest.TestCase):
    def setUp(self):
        self.budget = (Path(__file__).resolve().parents[2] / 'docs/local-mvp-preparation-budget.json').read_bytes()
        self.reports = {}
        def sample(mode, n):
            fresh = mode == 'fresh'
            return dict(mode=mode, repetition=n, status='passed', seconds=2 if fresh else 1,
                        work=dict(reused=not fresh, discoveryExecuted=fresh, materializationExecuted=fresh, toolBuildsExecuted=fresh))
        for name, project in [('small','App/App.csproj'),('serilog','src/Serilog/Serilog.csproj')]:
            self.reports[name] = dict(complete=True,purpose='calibration',repetitions=5,
                entries=[dict(project=project,globalProperties=dict(Configuration='Release',TargetFramework='net10.0'))],
                sourceIdentityAfterWarmup='source',sourceIdentityAfter='source',toolsAfterWarmup='tools',toolsAfter='tools',
                seed=dict(work=dict(reused=False,discoveryExecuted=True)),
                warmup=[sample(mode,0) for mode in ('fresh','reuse')],
                samples=[sample(mode,n) for n in range(1,6) for mode in ('fresh','reuse')],
                revision='candidate',sdkRoot=str(SDK),python='python',machine='arm64',platform='macOS')
        self.e2e = dict(accepted=True,adapterRevision='candidate',revision=json.loads(self.budget)['workloads']['serilog']['revision'],summaries={},
            samples=[dict(case=case,system=system,repetition=n,status='passed') for case in ('fresh','unchanged','sourceEdited','recovered') for system in ('ordinary','bazel') for n in range(1,6)])

    def test_recomputes_budget_instead_of_trusting_report_summary(self):
        self.reports['small']['summary']={'medianReuseToFreshRatio':99}
        self.assertTrue(evaluate(self.budget,self.reports,self.e2e)['performanceQualified'])
        for s in self.reports['small']['samples']:
            if s['mode']=='reuse':s['seconds']=3
        self.assertFalse(evaluate(self.budget,self.reports,self.e2e)['performanceQualified'])

    def test_incomplete_duplicate_failed_or_invalid_samples_reject(self):
        mutations = [lambda r:r['samples'].pop(), lambda r:r['samples'].__setitem__(0,copy.deepcopy(r['samples'][1])),
            lambda r:r['samples'][0].update(status='failed'),lambda r:r['samples'][0].update(seconds=float('nan')),
            lambda r:r['samples'][1]['work'].update(discoveryExecuted=True),lambda r:r.update(toolsAfter='changed')]
        for mutate in mutations:
            reports=copy.deepcopy(self.reports);mutate(reports['small'])
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):evaluate(self.budget,reports,self.e2e)

    def test_changed_budget_and_wrong_candidate_reject(self):
        with self.assertRaisesRegex(ValueError,'predeclared'):evaluate(self.budget+b' ',self.reports,self.e2e)
        self.e2e['adapterRevision']='another'
        with self.assertRaisesRegex(ValueError,'same-candidate'):evaluate(self.budget,self.reports,self.e2e)

    def test_missing_build_test_sample_rejects(self):
        self.e2e['samples'].pop()
        with self.assertRaisesRegex(ValueError,'Build/Test samples'):evaluate(self.budget,self.reports,self.e2e)
