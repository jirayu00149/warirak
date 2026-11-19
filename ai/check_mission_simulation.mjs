// Hand-built development cases, never a replacement for frozen validation/test evaluation.
import assert from'node:assert/strict';
import {MissionPoolEnv,MISSION_ENV,missionRequest}from'./navigation_mission_env.mjs';
const create=(patch={})=>new MissionPoolEnv(7,{profile:'stress',record:true,fixture:{x:5,y:3,heading:0,target:{x:9,y:3,class_id:0},obstacles:[],leftGain:1,rightGain:1,drift:{x:.08,y:0},delayTicks:0,positionNoise:0,velocityNoise:0,headingNoise:0,clearanceNoise:0,sensorDropout:0,targetDropout:0,bearingNoise:0,rangeNoise:0,...patch}});
const step=(e,action)=>e.step(missionRequest(e.steps,e.now(),action)),warm=e=>(step(e,'STOP'),e);
const report={schema:'warirak.mission-sim-development-cases.v1',environment:MISSION_ENV,source:'simulation',fixture_used:true,independent_validation:false,independent_test:false,training_started:false,training_protocol_frozen:false,controller:'hand-coded synthetic feedback, not a trained AI policy',hardware_calibrated:false,physical_motor_transport:false,production_runtime_supported:false,field_validated:false,population_collision_rate_measured:false,cases:[]};
for(const drift of [{x:.08,y:0},{x:-.08,y:0},{x:0,y:.08},{x:0,y:-.08}]){
 const hold=warm(create({drift})),stop=warm(create({drift})),anchor={x:hold.x,y:hold.y};
 for(let i=0;i<150;i++){step(hold,'HOLD');step(stop,'STOP');}
 const held=Math.hypot(hold.x-anchor.x,hold.y-anchor.y),neutral=Math.hypot(stop.x-anchor.x,stop.y-anchor.y);
 assert.ok(held<neutral*.5&&hold.mode==='HOLD');
 report.cases.push({name:'declared_current_position_feedback',current_mps:drift,seconds:15,stop_displacement_m:neutral,hold_displacement_m:held,hold_mode:hold.mode,ideal_extra_sensors:true,assertion_passed:true});
}
{
 const e=create({x:.195,drift:{x:-.08,y:0}});step(e,'STOP');assert.equal(e.collisions,1);report.cases.push({name:'stop_still_drifts_into_wall',collision_in_this_fixture:true,passive_current_retained:true,assertion_passed:true});
}
{
 const e=warm(create({delayTicks:2}));step(e,'HOLD');e.setFaults({manual_override:true});step(e,'HOLD');assert.equal(e.mode,'MANUAL_OVERRIDE');assert.equal(e.trace.at(-1).applied.left,0);assert.equal(e.trace.at(-1).applied.right,0);assert.equal(e.queue.length,0);report.cases.push({name:'manual_cancels_pending_hold',mode:e.mode,autonomous_output_zero:true,assertion_passed:true});
}
{
 const e=warm(create());e.setFaults({rear_unknown:true});step(e,'HOLD');assert.equal(e.mode,'HOLD_UNAVAILABLE');report.cases.push({name:'missing_rear_evidence',mode:e.mode,operator_assistance_required:!!e.latched,assertion_passed:true});
}
for(const fault of ['jammed','feedback_loss']){
 const e=warm(create({drift:{x:0,y:0}}));e.setFaults({[fault]:true});for(let i=0;i<25;i++)step(e,'FORWARD');
 const expected=fault==='jammed'?'RECOVERY_REQUIRED':'ACTUATION_UNAVAILABLE';assert.equal(e.mode,expected);report.cases.push({name:fault,mode:e.mode,reason:e.reason,automatic_recovery_implemented:false,assertion_passed:true});
}
{
 const e=warm(create({delayTicks:6}));for(let i=0;i<9;i++)step(e,'FORWARD');assert.equal(e.mode,'ACTUATION_UNAVAILABLE');assert.ok(e.trace.every(r=>r.applied.left===0));report.cases.push({name:'latency_exceeds_request_lifetime',delay_ms:600,request_ttl_ms:400,mode:e.mode,reason:e.reason,ttl_extended:false,assertion_passed:true});
}
report.all_passed=report.cases.every(c=>c.assertion_passed);console.log(JSON.stringify(report,null,2));
