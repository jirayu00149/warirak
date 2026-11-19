import test from 'node:test';
import assert from 'node:assert/strict';
import {validReportDate,reportFilters,periodSummary,reportLink,reportCsv} from '../frontend/reporting.js';

test('report URLs accept only supported dates, periods and boat identifiers',()=>{
 const today='2026-10-28';
 assert.equal(validReportDate('2024-02-29',today),true);
 for(const value of ['2026-02-29','2026-02-30','2026-13-01','2026-10-29','2026-1-02','bad',null])assert.equal(validReportDate(value,today),false);
 assert.deepEqual(reportFilters('?date=2026-09-01&days=90&boat=boat-1',today),{date:'2026-09-01',days:90,boat:'boat-1'});
 assert.deepEqual(reportFilters('?date=invalid&days=365&boat=%3Cscript%3E',today),{date:today,days:7,boat:''});
 const filters={date:today,days:30,boat:'boat-2'};
 const link=reportLink(filters,'https://example.test/ignored');
 assert.equal(new URL(link).pathname,'/monitor');assert.equal(new URL(link).hash,'#reports');
 assert.deepEqual(reportFilters(new URL(link).search,today),filters);
 assert.equal(new URL(reportLink({...filters,boat:''},'https://example.test')).searchParams.has('boat'),false);
});

test('period totals count all daily confirmations and deduplicate missions spanning days',()=>{
 const rows=[{date:'2026-10-27',total:3,bottles:2,caps:1,unknown:0,estimated:1,mission_ids:['a','b']},{date:'2026-10-28',total:2,bottles:0,caps:1,unknown:1,mission_ids:['b','c']}];
 assert.deepEqual(periodSummary(rows),{total:5,bottles:2,caps:2,unknown:1,estimated:1,missions:3});
 assert.deepEqual(periodSummary([]),{total:0,bottles:0,caps:0,unknown:0,estimated:0,missions:0});
 assert.throws(()=>periodSummary([{total:1,bottles:0,caps:0,unknown:0}]));
 assert.throws(()=>periodSummary([{total:-1,bottles:-1}]));
 assert.throws(()=>periodSummary([{total:1.5,bottles:1.5}]));
});

test('report CSV carries the same date and boat scope with Thai timezone and spreadsheet escaping',()=>{
 const csv=reportCsv([{date:'2026-10-28',total:3,bottles:1,caps:1,unknown:1}], '="test"');
 assert.equal(csv[0],'\ufeff');
 assert.equal(csv.split('\r\n').length,2);
 assert.ok(csv.includes('"Asia/Bangkok","hardware"'));
 assert.ok(csv.includes('"\'=""test"""'));
 assert.ok(csv.endsWith('"3","1","1","1"'));
});
