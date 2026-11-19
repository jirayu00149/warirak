import assert from'node:assert/strict';
import{MissionPoolEnvR2,MISSION_ENV_R2,missionRequestR2}from'./navigation_mission_env_r2.mjs';
const create=(patch={})=>new MissionPoolEnvR2(7,{profile:'stress',record:true,fixture:{x:5,y:3,heading:0,target:{x:9,y:3,class_id:0},obstacles:[],leftGain:1,rightGain:1,drift:{x:.08,y:0},delayTicks:0,positionNoise:0,velocityNoise:0,headingNoise:0,clearanceNoise:0,sensorDropout:0,targetDropout:0,bearingNoise:0,rangeNoise:0,...patch}});
const step=(e,action)=>e.step(missionRequestR2(e.steps,e.now(),action)),warm=e=>(step(e,'STOP'),e);
const report={schema:'warirak.mission-sim-r2-development-cases.v1',environment:MISSION_ENV_R2,source:'simulation',fixture_used:true,independent_validation:false,independent_test:false,training_started:false,training_protocol_frozen:false,physical_motor_transport:false,field_validated:false,population_success_or_collision_rate_measured:false,cases:[]};
{
 const e=warm(create());step(e,'FORWARD');const captured=e.observe().sensors.range_evidence.captured_at_ms;e.setFaults({range_packet_loss:true});step(e,'FORWARD');assert.equal(e.mode,'WAIT_RANGE_UPDATE');assert.equal(e.trace.at(-1).applied.left,0);
 const evidence=e.observe().sensors.range_evidence;assert.equal(evidence.captured_at_ms,captured);
 report.cases.push({name:'missing_frame_keeps_original_clock',mode:e.mode,range_evidence:evidence,output_zero:true,passed:true});
 e.setFaults({range_packet_loss:false});e.step();assert.equal(e.mode,'WATCHDOG_STOP');step(e,'FORWARD');assert.equal(e.mode,'TRACKING');report.cases.push({name:'fresh_frame_requires_new_request',mode_without_new_request:'WATCHDOG_STOP',mode_after_new_request:e.mode,passed:true});
}
{
 const e=warm(create());e.setFaults({range_packet_loss:true});for(let i=0;i<5;i++)step(e,'FORWARD');assert.equal(e.mode,'FAULT_STOP');report.cases.push({name:'continuous_missing_range',mode:e.mode,reason:e.reason,evidence:e.observe().sensors.range_evidence,passed:true});
}
for(const intermittent of [false,true]){
 const e=warm(create({drift:{x:0,y:0},positionNoise:.02,velocityNoise:.008,headingNoise:.025}));e.setFaults({jammed:true});
 for(let i=0;i<75&&e.mode!=='PROGRESS_UNCERTAIN';i++){if(intermittent)e.setFaults({range_packet_loss:i%5===0});step(e,'FORWARD');}
 assert.equal(e.mode,'PROGRESS_UNCERTAIN');assert.equal(e.trace.at(-1).applied.left,0);const evidence=e.observe().mission.progress_evidence;assert.equal(evidence.confirmed_stall,false);
 report.cases.push({name:intermittent?'inconclusive_progress_with_brief_packet_gaps':'inconclusive_progress_at_unchanged_uncertainty',mode:e.mode,velocity_uncertainty_mps:e.velocityNoise,progress_evidence:evidence,passed:true});
}
{
 const e=warm(create({drift:{x:0,y:0},positionNoise:.02,velocityNoise:.008,headingNoise:.025}));for(let i=0;i<25;i++)step(e,'FORWARD');assert.equal(e.mode,'TRACKING');assert.ok(e.trace.some(r=>r.before.mission.progress_evidence.status==='independent_forward_progress_observed'));report.cases.push({name:'independent_forward_progress_observed',mode:e.mode,progress_observed_in_trace:true,passed:true});
}
{
 const e=warm(create({delayTicks:2}));step(e,'HOLD');e.setFaults({manual_override:true,range_packet_loss:true});step(e,'HOLD');assert.equal(e.mode,'MANUAL_OVERRIDE');assert.equal(e.trace.at(-1).applied.left,0);assert.equal(e.trace.at(-1).applied.right,0);report.cases.push({name:'manual_override_during_data_loss',mode:e.mode,autonomous_output_zero:true,passed:true});
}
report.all_passed=report.cases.every(r=>r.passed);console.log(JSON.stringify(report,null,2));
