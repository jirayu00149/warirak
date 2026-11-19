"""Package the reviewed temporal-navigation experiment; never activate it as the deployed policy."""
from pathlib import Path
import datetime,hashlib,json,shutil,zipfile

root=Path(__file__).resolve().parents[1];run=root/'work/navigation-memory-v3';out=root/'outputs';assets=root/'frontend/assets'
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
protocol=read(run/'protocol.json');selection=read(run/'selection.json');evaluation=read(run/'evaluation.json');diagnosis=read(run/'failure-diagnostics.json');state=read(run/'status.json')
assert state['phase']=='candidate_ready_for_review' and state['selected_episodes']==selection['selected_episodes']==evaluation['selected_episodes']==40000
assert selection['test_used_for_selection'] is False and evaluation['test_used_for_selection'] is False
assert protocol['frozen_before_training'] and protocol['baseline_sha256']==sha(assets/'navigation-policy.json')
for file,digest in protocol['source_sha256'].items():assert sha(root/file)==digest,file
assert any(t['eligible'] and t['episodes']==40000 for t in selection['trials'])
for controller in ['baseline','candidate','rules']:
 for profile in ['nominal','stress']:
  r=evaluation[controller][profile];assert r['collections']+r['collisions']+r['timeouts']==r['episodes']==1000
  assert r['source']=='simulation' and not r['control_enabled'] and not r['real_world_validated']
report=dict(schema='warirak.navigation-experiment-outcome.v1',created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),experiment='navigation-memory-v3',environment=protocol['environment'],source='simulation',outcome='research_candidate_selected_not_deployed',selected_episodes=40000,candidates_trained=[16000,40000],validation_gate_passed=True,production_promoted=False,production_policy_unchanged=True,production_runtime_supported=False,real_world_validated=False,control_enabled=False,test_used_for_selection=False,selection=selection,evaluation=evaluation,failure_diagnostics=diagnosis,engineering_review={'decision':'do_not_deploy','reasons':['Validation stress collision25.8% and nominal17.4% already too high for operational readiness','Selected candidate still collides272/1000 in held-out synthetic stress cases','Several inspected validation failures drift into obstacles while commanded STOP','New schema/runtime is incompatible with the deployed 5-action policy; no hardware calibration'],'criterion_note':'Frozen comparative validation gates selected a research candidate; they were not a field-safety certification. Engineering refusal to deploy does not change the candidate selection or select a different model on test.'},limitations=['Synthetic target observations/range; no YOLO video or boat-camera validation','Comparison uses identical new memory-v3 physics and supervisors for all controllers; original v1 simulation98.1% is a different setting','Inspected six validation failures are purposive examples, not a full failure-cause rate estimate','No new production policy or real motor commands'],protocol_sha256=sha(run/'protocol.json'),policy_sha256=sha(run/'navigation-memory-policy.json'),deployed_policy_sha256=sha(assets/'navigation-policy.json'))
def row(label,profile):
 b=evaluation['baseline'][profile];c=evaluation['candidate'][profile]
 return f"| {label} | {b['collections']}/1000 ({b['success_rate']*100:.1f}%) | {c['collections']}/1000 ({c['success_rate']*100:.1f}%) | {b['collisions']}/1000 | {c['collisions']}/1000 | {c['timeouts']}/1000 |"
card=f'''# ผลทดลองการเดินเรือแบบมีความจำ — memory-v3

วารีรักษ์ คณะวิศวกรรมศาสตร์ มหาวิทยาลัยทักษิณ — 28 ตุลาคม 2569

## สรุปการตัดสินใจ

เลือกผู้สมัคร40000รอบจากเกณฑ์validationที่กำหนดก่อนฝึกได้ แต่ **ยังไม่แทนที่นโยบายที่ใช้งานบนเว็บ** เพราะอัตราชนยังสูงและรูปแบบคำสั่งใหม่ต้องมีruntimeแยก ผลทั้งหมดเป็นการจำลอง ยังไม่ได้ต่อมอเตอร์หรือทดสอบเรือจริง

## สิ่งที่เปลี่ยนในสภาพแวดล้อม

ใช้ `warirak-pool-memory-v3` และนโยบาย `warirak.navigation-memory-policy.v1` แยกจากรุ่นเดิม เพิ่มSTOPที่แรงขับเป็นศูนย์ ประวัติคำสั่งที่ส่งสองครั้งล่าสุด และความจำด้านที่เคยเห็นเป้าหมายไม่เกินสองก้าว ไม่มีตำแหน่งจริงของเรือหรือเป้าหมายในภาพสังเกตที่ผู้เรียนได้รับ มี19440สถานะและ6คำสั่ง

แก้ช่วงเริ่มหน่วงคำสั่งให้เป็นSTOP และให้STOPล้างคิว ตรวจระยะซ้ำทั้งก่อนส่งและก่อนใช้คำสั่งที่ค้างในคิว การหยุดไม่ทำให้กระแสน้ำหายไป เรือจำลองยังลอยไปชนได้ ต้องแยกการหยุดมอเตอร์ออกจากการรักษาตำแหน่ง

โค้ดผ่าน11การทดสอบใหม่ รวมถึงการคงผลเมื่อฝึกต่อจากcheckpoint การล้างคิว การตรวจคำสั่งเก่า ภาพจำที่หมดอายุ และการชนจากกระแสน้ำขณะSTOP ทั้งชุดJavaScript49รายการผ่าน

## วิธีฝึกและเลือก

เริ่มจากตารางเดิมโดยแปลงคำสั่งอย่างชัดเจน ฝึก16000และ40000รอบ ใช้ภาพสังเกตสังเคราะห์ ผสมสนามปกติ25%และสนามยาก75% alpha0.04 gamma0.97 แต่ละสนามสูงสุด320ก้าว

แช่แข็งprotocolและค่าแฮชซอร์สก่อนเริ่ม ข้อมูลฝึกเริ่มseed12000000 ส่วนvalidationใช้nominal14000000/stress14500000อย่างละ500สนาม เกณฑ์คือสนามยากสำเร็จเพิ่มอย่างน้อย1จุดเปอร์เซ็นต์ ชนเพิ่มไม่เกิน0.5จุด และสนามปกติสำเร็จลดไม่เกิน1จุด/ชนเพิ่มไม่เกิน0.5จุด เลือกผู้สมัครจากvalidationเท่านั้น จากนั้นจึงประเมินสนามtestที่ไม่ได้ใช้เลือก:nominal16000000/stress16500000อย่างละ1000สนาม

ผู้สมัคร16000รอบผ่านเกณฑ์เปรียบเทียบเช่นกัน แต่40000รอบได้คะแนนvalidationสนามยากดีกว่าตามกติกาที่ระบุไว้ ไม่ได้เปลี่ยนตัวเลือกเมื่อเห็นtest

## ผลบนสนาม test สังเคราะห์ของรุ่นนี้

| สนาม | รุ่นเดิมสำเร็จ | รุ่นทดลองสำเร็จ | รุ่นเดิมชน | รุ่นทดลองชน | รุ่นทดลองหมดเวลา |
|---|---:|---:|---:|---:|---:|
{row('ปกติ','nominal')}
{row('ยาก','stress')}

ทั้งคู่ใช้ฟิสิกส์และตัวกำกับการหยุดของmemory-v3เดียวกัน รุ่นเดิมใช้ตารางที่เผยแพร่อยู่โดยแปลงหมายเลขคำสั่ง ไม่เปรียบตัวเลขนี้ตรงกับผล98.1%ของสนามv1เดิม การมองเห็นและระยะในที่นี้เป็นค่าจำลอง ไม่มีการรันYOLOกับวิดีโอเรือ

แม้ดีขึ้นเมื่อเทียบกันในเงื่อนไขนี้ แต่การชน27.2%ในสนามยากยังสูง ไม่ใช่ผลรับรองความปลอดภัยหรือความพร้อมใช้งาน แม้ดูเฉพาะvalidationก่อนtestก็มีการชน25.8%ในสนามยากและ17.4%ในสนามปกติ จึงยังไม่ควรนำไปสั่งมอเตอร์

## ตัวอย่างความล้มเหลวและงานถัดไป

ตรวจตัวอย่างvalidationที่ชนอย่างละ3ฉากในสองprofile พบว่าทั้ง6ตัวอย่างมีช่วงใช้STOPต่อเนื่อง20–100ก้าวก่อนชน โดยกระแสน้ำยังทำให้เคลื่อนที่ ตัวอย่างเหล่านี้เลือกเพื่อดูเหตุล้มเหลว ไม่ใช่การวัดสัดส่วนสาเหตุทั้งหมด และไม่ใช่หลักฐานการเกิดเหตุบนเรือจริง

ขั้นถัดไปควรแยกสถานะหยุด/ลอยตามน้ำ/ติดค้าง ประเมินการเคลื่อนที่จากภาพและเซนเซอร์ และออกแบบการรักษาตำแหน่งหรือขอผู้ใช้ช่วยในกรณีที่ข้อมูลรอบเรือไม่พอ ต้องทดสอบฉากความผิดปกติและกติกาการหลบก่อนฝึกเพิ่ม ไม่วนเพิ่มจำนวนรอบจากสูตรเดิม

## ใช้แพ็กทดลอง

แพ็กมีซอร์สที่แช่แข็ง protocol ผลผู้สมัครทั้งสอง ตารางคะแนน แฟ้มนโยบายใหม่ และตัวอย่างเส้นทางที่ล้มเหลว สำหรับตรวจและทำซ้ำในซอฟต์แวร์เท่านั้น **ห้ามวางนโยบายนี้ทับ `frontend/assets/navigation-policy.json`** ตัวตรวจนโยบายเดิมตั้งใจไม่ยอมรับschemaใหม่นี้

ผลไม่มีความแม่นยำกล้อง ไม่มีการวัดFPSบนPi ไม่มีGPIO/serial/motor transport โมเดลตรวจจับpublic-v4และนโยบายที่หน้าเว็บใช้ยังคงเดิม
'''
pack=out/'Warirak_Navigation_Memory_v3_Experiment';pack.mkdir(parents=True,exist_ok=True)
for name in ['protocol.json','selection.json','evaluation.json','navigation-memory-policy.json','candidate-16000.json','candidate-40000.json','failure-diagnostics.json']:
 target=pack/'experiment'/name;target.parent.mkdir(exist_ok=True);shutil.copy2(run/name,target)
for file in run.glob('diagnostic-*.json'):shutil.copy2(file,pack/'experiment'/file.name)
for file in list(protocol['source_sha256'])+['ai/navigation-memory-v3-protocol.json','frontend/autonomy.js','frontend/assets/navigation-policy.json','tests/navigation-memory.test.mjs','tests/navigation-memory-training.test.mjs','LICENSE','THIRD_PARTY_NOTICES.md']:
 target=pack/file;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(root/file,target)
(pack/'REPORT_TH.md').write_text(card,encoding='utf-8');(pack/'experiment-outcome.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
checks={f.relative_to(pack).as_posix():sha(f) for f in pack.rglob('*') if f.is_file() and f.name!='checksums.json'};(pack/'checksums.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
target=out/'Warirak_Navigation_Memory_v3_Experiment.zip'
with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as archive:
 for f in sorted(pack.rglob('*')):
  if f.is_file():archive.write(f,pack.name+'/'+f.relative_to(pack).as_posix())
with zipfile.ZipFile(target) as archive:
 for name,digest in checks.items():assert hashlib.sha256(archive.read(pack.name+'/'+name)).hexdigest()==digest,name
assert target.stat().st_size<24*1024*1024
(assets/'navigation-memory-v3-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');(assets/'NAVIGATION_MEMORY_V3_REPORT_TH.md').write_text(card,encoding='utf-8');shutil.copy2(target,assets/target.name)
state.update(phase='reviewed_not_promoted',review_complete=True,delivery_complete=True,outcome=report['outcome'],production_policy_unchanged=True,reviewed_at=report['created_at'])
(run/'status.json').write_text(json.dumps(state,indent=2),encoding='utf-8')
audit={'reviewed_at':report['created_at'],'promoted':False,'research_gate_passed':True,'package':str(target),'package_sha256':sha(target),'report_sha256':sha(assets/'navigation-memory-v3-report.json'),'archived_hashes_verified':len(checks),'source_hashes_match_frozen_protocol':True,'production_policy_unchanged_sha256':sha(assets/'navigation-policy.json')}
(out/'Warirak_Navigation_Memory_v3_Package_Audit.json').write_text(json.dumps(audit,indent=2),encoding='utf-8');print(json.dumps({'research_gate_passed':True,'production_promoted':False,'selected_episodes':40000,'test_stress_success':evaluation['candidate']['stress']['success_rate'],'test_stress_collision':evaluation['candidate']['stress']['collision_rate'],'package_bytes':target.stat().st_size,'archived_hashes_verified':len(checks)}))
