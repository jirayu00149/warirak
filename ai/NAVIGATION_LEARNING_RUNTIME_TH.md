# Runtime ฝึกจำลอง Node/Python

เพิ่ม runtime ที่เชื่อม actor request → ก้าวฟิสิกส์ R2 → duration credit → replay/update → commit/checkpoint/journal ครบวงจร ผ่าน targeted tests ใหม่ Python 5 รายการและ Node 4 รายการ ไม่มีการรันชุดเก่าซ้ำ หลักฐานอยู่ที่ `work/navigation-runtime-preflight` และ `outputs/Warirak_Navigation_Runtime_Audit.json` ทั้งหมดเป็นการตรวจซอฟต์แวร์ ยังไม่ใช่รอบฝึกจริงหรือผลความสามารถของ AI

## ข้อมูลและเวลา

Node `navigation_learning_runtime.mjs` เป็นผู้เรียกตัวจำลองและ bridge ส่วน Python `warirak_ai.navigation_runtime` รับ JSONL RPC ในเครื่องตามลำดับและขนาดที่จำกัด Actor รับเฉพาะ canonical request ไม่รับพิกัดโลกหรือวัตถุ environment ใช้ model schema ของ duration learner และตรวจ request/session/vector/mask/clock bindings เดิม ไม่มี network, GPIO, serial หรือการส่งคำสั่งมอเตอร์จริง

Python ตรวจคำขอที่ส่งจริงกับ proposal และ mask ตรวจเวลา/TTL 400 มิลลิวินาที แล้วประกอบ duration credit คาดหมายใหม่จากทุก physical ledger เพื่อเทียบกับข้อมูลของ bridge ช่วงรอไม่ถูกปลอมเป็น STOP และ prefix ที่ยังไม่มีคำขอยังคงมีบัญชีของตนเอง ผลปลายทางและรางวัลต้องตรงกับทุกก้าวที่ยอมรับก่อน commit

ตรวจสถานะ assistance จาก mission ในเฟรมถัดไป ไม่อาศัยเพียง mode ของคำสั่งที่ส่ง เพราะ receiver อาจปฏิเสธคำสั่งที่หมดอายุภายหลังแล้วเปลี่ยนสถานะ รางวัล assistance คิดครั้งแรกครั้งเดียว ส่วนการชนหลัง STOP/assistance ยังคงอยู่

การคำนวณเป็น synchronous บนนาฬิกาจำลอง ไม่ขยับเวลาฟิสิกส์ระหว่างที่เครื่องรอ Python จึงไม่ใช่ความหน่วงกล้อง/เครือข่ายหรือ Raspberry Pi FPS ความหน่วง actuator 0/300/600 มิลลิวินาทีของ R2 ยังคงเป็นคนละเรื่องกับ inference wait

## Schedule ที่กู้ได้

Epsilon คำนวณจาก `model.choices` ที่เก็บใน checkpoint โดยนับ proposal ของ actor ส่วนจังหวะ update คำนวณจาก `replay.total_added` ซึ่งนับเครดิตของคำขอจริง ค่าชุดตรวจนี้อัปเดตทุกสี่เครดิตหลัง warmup 256 เครดิต ไม่ได้นับเป็นทุกสี่ก้าวฟิสิกส์ เมื่อเครดิตกินเวลาหลายก้าวจำนวนเครดิตกับ physical steps จึงต่างกัน ต้องกำหนดความหมายนี้ใน protocol ฝึกฉบับจริงด้วย

เมื่อเริ่ม process ต้องตรวจ source hashes และระบุ initialize หรือ resume อย่างชัดเจน มี lifetime owner lock แยกจาก commit lock การเปิด runtime ซ้ำไม่สามารถโหลด store ที่มีเจ้าของอยู่ได้ Lock ค้างหลัง process ตายยังต้องตรวจ PID/เวลาเริ่มและ checkpoint ก่อนจัดการ ไม่ลบ lock โดยอัตโนมัติ

## ผล การกู้ และ snapshot

ใช้ JournaledEpisodeCommitStore เก็บทุกผลและ hash chain พร้อม checkpoint/cursor ที่ commit แล้ว หากหยุดกลาง episode จะไม่บันทึกว่าจบ episode และไม่ข้าม seed การกู้ใน process ใหม่เริ่ม seed ที่ยังไม่ commit จากโลกที่สร้างด้วย seed เดิมและสถานะตัวเรียนที่ commit ล่าสุด ไม่ใช่การกู้โลกกลาง episode

ชุดตรวจหยุดอย่างชัดเจนหลังหก physical steps: หนึ่ง episode สี่ก้าว commit แล้ว อีกสองก้าวยังไม่ commit เปิด Python ใหม่แล้วเริ่ม seed ที่สองซ้ำ ผลราย episode และ fingerprint ของสถานะตัวเรียนทั้งหมดตรงกับเส้นทางที่รันต่อเนื่อง ตรวจทั้ง network/target/replay/Adam/RNG/cursor ตาม fingerprint จากข้อมูลจริงในหน่วยความจำ นี่เป็นการหยุด process อย่างสุภาพ ไม่ใช่การทดสอบ OS hard kill หรือไฟดับ

Snapshot ตามรอบที่ระบุใน protocol จะคัดลอกจาก checkpoint ที่ commit แล้ว ตรวจ hash และเก็บนอกพื้นที่ล้าง checkpoint ย้อนหลัง กำหนดได้ไม่เกินสี่ snapshot พร้อมพื้นที่ดิสก์สำรอง หาก snapshot ที่ควรมีหายไปจะเป็นปัญหาที่ต้องตรวจ ไม่สร้าง snapshot รุ่นเก่าจากน้ำหนักรุ่นใหม่ขึ้นมาแทน เมื่อจบ budget จริงจะอยู่ที่ `training_complete_needs_validation_review` ไม่มีการเปิด test หรือเผยแพร่อัตโนมัติ

## ขอบเขตการตรวจ

ใช้ seed 11500/11501 เป็นฟิกซ์เจอร์ซอฟต์แวร์ใหม่ใกล้ตลิ่ง กำหนดตำแหน่งให้กระแสน้ำเดิมพาไปชนในสี่ก้าว โดยคง current/noise/dropout/gain/actuator delay ที่ R2 สร้างไว้ ใช้ทดสอบ IPC เครดิตช่วงรอ commit และ process restart ไม่ใช่ตัวอย่างสุ่มสำหรับสรุปอัตราชนหรือคุณภาพนโยบาย และไม่ได้เล่น full horizon 960 ก้าว

รอบ end-to-end ทั้งสอง episode ยังไม่ถึง warmup จึงไม่มี optimizer update ในเส้นทางนั้น มีหนึ่ง gradient update จากข้อมูลสังเคราะห์ใน Python core test เพื่อยืนยัน cadence เท่านั้น ไม่ได้นำ checkpoint ชั่วคราวไปเป็นโมเดลโครงงานหรือเผยแพร่ การทดสอบ packet ที่เสียและ duplicate owner เป็นกรณีเชิงลบ ไม่ใช่ episode ที่นับว่าทำสำเร็จ

## ก่อนเริ่มรอบวิจัยจริง

คำสั่ง runtime รองรับ `initialize|resume <protocol.json> <run-root>` แต่ protocol ชุดตรวจนี้อนุญาตเฉพาะ software preflight โหมดจริงต้องมี protocol คนละฉบับที่ครบ source hashes, งบฝึก, schedule, snapshots, training/validation/test ที่ไม่ซ้อนกัน, selection ที่ไม่ใช้ test และอ้างอิง runtime audit ที่ทบทวนแล้ว

งานต่อไปคือ read-only snapshot evaluator และการเปรียบเทียบกฎ/v1/v2 ภายใต้ข้อมูลและตัวกำกับเดียวกัน โดยไม่เปลี่ยน weights, replay, optimizer หรือ RNG ระหว่างประเมิน และแช่แข็งเกณฑ์/แผนจริงก่อนเริ่มฝึก ไม่ลดความยากหรือเกณฑ์เดิมเพื่อให้คะแนนดูดี

รุ่นตรวจจับยังเป็น public-v4 ตรง release.json/D1 ที่อ่านอย่างเดียว นโยบายห้าคำขอบนเว็บไม่เปลี่ยน ไม่มี deployment หรือมอเตอร์จริง การผ่าน runtime tests ไม่ใช่ความพร้อมภาคสนาม
