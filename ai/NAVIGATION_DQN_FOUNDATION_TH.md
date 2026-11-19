# ฐาน Double DQN สำหรับข้อมูลประวัติ

ส่วนนี้เพิ่มตัวเรียนและการบันทึกสถานะสำหรับงานวิจัยในตัวจำลอง ผ่านการตรวจเฉพาะส่วนใหม่ Python 18 รายการและ Node 4 รายการ ยังไม่มีนโยบายที่ฝึกจากการขับเรือ ไม่มีการประเมิน collection/collision และไม่มีการควบคุมมอเตอร์จริง ใช้ข้อมูลสังเคราะห์เพื่อทดสอบสมการ ซอฟต์แวร์ และการกู้สถานะเท่านั้น หลักฐานอยู่ที่ `work/navigation-dqn-preflight` และ `outputs/Warirak_Navigation_DQN_Foundation_Audit.json`

## สถาปัตยกรรมและการจำกัดคำขอ

ใช้ข้อมูลประวัติเดิม 234 ค่า เข้าโครงข่าย 234→64→64→7 พร้อม ReLU รวม 19,655 พารามิเตอร์ ทำงานบน CPU แบบ float32 หลังตรวจ digest ของเวกเตอร์ binary64 เดิมแล้ว รายละเอียดที่แช่แข็งอยู่ใน `navigation-dqn-recipe.json` ใช้ Adam, SmoothL1 loss, gradient clipping, target network และ replay แบบวงแหวนไม่เกิน 8,192 รายการ ไม่มีการเปลี่ยน encoder หรือฟิสิกส์ R2

การสำรวจและ greedy เลือกได้เฉพาะเจ็ดคำขอเดินเรือที่ action mask เดิมอนุญาต Double DQN เลือกคำขอถัดไปจาก online network ภายใน mask แล้วอ่านค่าของคำขอนั้นจาก target network จึงไม่ให้ค่าของคำขอที่ห้ามไหลเข้าเป้าหมายการเรียนรู้ เฉพาะ collision, collection และ time limit เต็มเท่านั้นที่หยุด bootstrap

ข้อมูล transition ต้องเป็น record ที่ต่อกันตามเวลาเดิม 100 มิลลิวินาที คำขอที่บันทึกต้องอยู่ใน mask ของสถานะเดิม หาก epoch เปลี่ยน สถานะถัดไปต้องล้างประวัติและใช้ previous_request=UNKNOWN แต่ยังรับรางวัลและเรียนรู้ค่าต่อได้ การเปลี่ยน authority จึงไม่ถูกตีความว่าเรือหยุดหรือ episode สิ้นสุด ไม่อนุญาตให้ระบุ assistance เป็น terminal เพื่อหลบการนับการชนจากการลอย

สมการรางวัลสำหรับ bridge ที่จะทำภายหลังยังคง R2: 3 เท่าของระยะที่เข้าใกล้เป้าหมาย −0.015 ต่อ step +40 เมื่อเก็บได้ −30 เมื่อชน −10 เมื่อเข้าสู่ assistance ครั้งแรก พิกัดโลกใช้คำนวณรางวัลเท่านั้น ไม่ส่งเข้า actor ขณะนี้ยังไม่ได้เชื่อมสมการนี้กับ episode driver หรือสร้าง transition จาก rollout จริง การทดสอบนี้ใช้รางวัลตัวเลขที่กำหนดขึ้น

## การสุ่มและ checkpoint

ใช้ RNG ของ Python สำหรับการสำรวจ และ CPU Torch generator แยกสำหรับสุ่ม replay การเริ่มน้ำหนักไม่ขยับ global RNG ของผู้เรียกและไม่จัดสรร CUDA โครงข่ายไม่มี dropout หรือชั้นสุ่มระหว่าง forward การตรวจความต่อเนื่องจำกัดที่ runtime CPU และเวอร์ชันเดียวกัน ไม่รับรองความเหมือนข้ามเครื่อง เวอร์ชัน หรือ CPU/GPU ตามข้อจำกัดของ [PyTorch 2.7](https://docs.pytorch.org/docs/2.7/notes/randomness.html)

Checkpoint เก็บ online/target network, Adam slots, replay ring/cursor, RNG ทั้งสอง, ตัวนับ และ cursor ระหว่าง episode อย่างชัดเจน ใช้ไฟล์ pending ก่อนแทนไฟล์จริง จำกัดขนาด 64 MiB และตรวจ hash ที่ผู้เรียกเชื่อถือก่อนโหลด ต้องตรงกับ protocol, layout, recipe และ runtime เดิม การโหลดใช้ CPU และ `weights_only=True` ตาม [เอกสาร torch.load](https://docs.pytorch.org/docs/2.7/generated/torch.load.html) ไม่เปิด unsafe pickle เพื่อเลี่ยงข้อผิดพลาด

ยังไม่รองรับการกู้กลาง episode และยังไม่ได้บันทึกสถานะโลก/นาฬิกา/RNG ของ Node plant ตัวรันในอนาคตต้อง commit ผลและ cursor ระหว่าง episode อย่างสอดคล้อง หากขัดข้องกลาง episode ต้องเริ่ม episode ที่ยังไม่ commit จาก seed เดิม โดยไม่ทิ้งผลที่ล้มเหลว ไม่ใช่เริ่มฝึกทั้งหมดจากศูนย์ การผ่านการกู้ตัวเรียนเพียงอย่างเดียวยังไม่ยืนยันความถูกต้องของตัวรันดังกล่าว

## สะพานข้อมูลที่ตรวจ

`warirak_ai/navigation_dqn_stream.py --preflight-stream` เป็น process JSONL ในเครื่องสำหรับตรวจ forward ของโครงข่ายที่สุ่มน้ำหนักเริ่มต้น รับไม่เกิน 32 ข้อความและตรวจเวลาจำลองเดิม session/record/epoch การซ้ำและการถอยหลัง เมื่อข้อมูลผิดจะปิด process และไม่ส่งข้อเสนอถัดไป คำตอบใช้ schema validation fixture ที่ถูกปฏิเสธโดยค่าเริ่มต้น ต้อง opt in เฉพาะการทดสอบ

สะพานนี้ไม่โหลด trained checkpoint ไม่เพิ่ม optimizer step และไม่ปรับเวลาเดิมให้สดเพราะรอ Python ฝั่ง Node ยังคงปฏิเสธคำตอบที่ถูก cancel หรือหมดอายุแล้ว ไม่มีการใช้ wall-clock นี้อ้างเป็นความหน่วง Raspberry Pi ไม่มี GPIO/serial ไม่มี watchdog ฮาร์ดแวร์ และไม่ได้แทน authority ของ R2

## ขอบเขตการตรวจและคิวถัดไป

แผน preflight กำหนด Python 18 กรณีและ Node 4 กรณี รวมสมการ masked target, terminal, การกัน operator, replay ที่จำกัดขนาด, finite gradients, target sync, RNG, การกู้ไฟล์แล้วทำสามขั้นถัดไปให้ตรงทุกค่า และ JSONL/cancel/expiry/duplicate ใช้เวกเตอร์สังเคราะห์ห้ารายการ ไม่มี plant rollout, dataset, validation/test partition หรือการวัดประสิทธิภาพนโยบาย จำนวน optimizer steps ใน unit tests ถูกจำกัดไว้ ไม่ใช่รอบฝึกโครงงานและไม่นำ checkpoint ชั่วคราวไปเผยแพร่

งานถัดไปคือ episode driver ที่ใช้ sidecar/encoder/ตัวกำกับเดิมและรางวัลตาม R2 จริง พร้อมตรวจ credit และผลปลายทางหลัง manual/disarm/cancel/assistance รวมการหน่วง 0/300/600 มิลลิวินาที การนับเวลา inference และการ commit/resume ระหว่าง episode จากนั้นจึงกำหนดงบฝึก schedule และแช่แข็ง protocol พร้อม seed/exposure registry และตัวอ้างอิงที่เข้าถึงข้อมูลเดียวกัน ก่อนเริ่มงานฝึกจริง

คง public-v4, นโยบายเดิมบนเว็บ, รหัสผู้ดูแล และการเอาหน้าสมาชิกออก ไม่มีการเปิด test หรือเปลี่ยน deployment จากการตรวจส่วนนี้ ความสำเร็จของ unit tests ไม่ใช่ความพร้อมภาคสนาม
