import unittest,tempfile,json,hashlib,zipfile,copy,types
from pathlib import Path
from PIL import Image
from warirak_ai import CLASSES
from warirak_ai.dataset import grouped_split,prepare,validate,yolo_values,safe_path,training_yaml
from warirak_ai.evaluate import report_from_metrics
from warirak_ai.infer import detection_event

class DatasetTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def project(self):
        records=[];payload={}
        for i in range(3):
            path=self.root/f'image{i}.png';Image.new('RGB',(80,60),(i*40,100,180)).save(path);data=path.read_bytes();id=f'image-{i}'
            records.append(dict(id=id,file=f'images/{id}.png',filename=path.name,extension='png',session_id=f'day-{i}',width=80,height=60,sha256=hashlib.sha256(data).hexdigest(),boxes=[dict(class_id=0,x=.1,y=.1,w=.3,h=.4),dict(class_id=1,x=.6,y=.6,w=.2,h=.2)],reviewed=True,negative=False))
            payload[f'images/{id}.png']=data
        archive=self.root/'project.zip'
        with zipfile.ZipFile(archive,'w')as z:
            z.writestr('annotations.json',json.dumps(dict(schema='warirak.project.v1',classes=CLASSES,images=records)))
            for name,data in payload.items():z.writestr(name,data)
        return archive,records
    def test_prepare_roundtrip_and_absolute_configuration(self):
        archive,_=self.project();out=self.root/'dataset';r=prepare(archive,out);self.assertTrue(r['valid'],r);self.assertEqual(r['counts'],dict(train=1,val=1,test=1));config=training_yaml(out,self.root/'runs/data.yaml');self.assertIn(str(out.resolve()),config.read_text());self.assertEqual(yolo_values(dict(class_id=0,x=.1,y=.2,w=.3,h=.4)),[0,.25,.4,.3,.4])
    def test_group_leakage_is_rejected(self):
        archive,_=self.project();out=self.root/'dataset';prepare(archive,out);manifest=json.loads((out/'manifest.json').read_text());manifest['images'][1]['session_id']=manifest['images'][0]['session_id'];(out/'manifest.json').write_text(json.dumps(manifest));self.assertFalse(validate(out)['valid'])
    def test_modified_labels_and_images_are_rejected(self):
        archive,_=self.project();out=self.root/'dataset';prepare(archive,out);label=next((out/'labels').rglob('*.txt'));original=label.read_text();label.write_text('0 0.5 0.5 0.9 0.9\n');self.assertFalse(validate(out)['valid']);label.write_text(original);image=next((out/'images').rglob('*.png'));image.write_bytes(b'not-an-image');self.assertFalse(validate(out)['valid'])
    def test_missing_review_and_destination_overwrite_are_rejected(self):
        archive,_=self.project();out=self.root/'dataset';prepare(archive,out)
        with self.assertRaises(ValueError):prepare(archive,out)
        with self.assertRaises(ValueError):safe_path(out,'../outside.jpg')
        with self.assertRaises(ValueError):safe_path(out,'images\\bad.jpg')
    def test_deterministic_split_and_minimum_groups(self):
        _,records=self.project();self.assertEqual(grouped_split(records),grouped_split(records[::-1]));self.assertEqual(set(grouped_split(records).values()),{'train','val','test'})
        with self.assertRaises(ValueError):grouped_split(records[:2])
    def test_absent_metrics_are_unavailable_not_overall_map(self):
        box=types.SimpleNamespace(ap_class_index=[0],mp=.9,mr=.8,map50=.85,map=.7,class_result=lambda _: (.9,.8,.85,.7));r=report_from_metrics(types.SimpleNamespace(box=box),'test.pt',{},640);self.assertIsNone(r['classes']['bottle_cap']);self.assertFalse(r['complete']);self.assertEqual(r['classes']['plastic_bottle']['precision'],.9)
    def test_detection_event_cannot_confirm_collection_or_enable_motors(self):
        e=detection_event(1,640,480,[dict(class_id=0,confidence=.9)],15);self.assertFalse(e['collection_confirmed']);self.assertFalse(e['control_enabled']);self.assertEqual(e['source'],'detector')

if __name__=='__main__':unittest.main()
