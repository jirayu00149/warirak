"""Export trained custom weights to NCNN; evaluate the exported model again."""
import argparse
from pathlib import Path
from . import CLASSES
from .evaluate import model_classes

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--weights',type=Path,required=True);p.add_argument('--imgsz',type=int,default=640);a=p.parse_args()
    if not a.weights.is_file():p.exit(2,'Provide your trained best.pt, not a placeholder.\n')
    from ultralytics import YOLO
    model=YOLO(str(a.weights))
    if model_classes(model)!=CLASSES:p.exit(2,'Model class names do not match the project dataset.\n')
    result=model.export(format='ncnn',imgsz=a.imgsz,device='cpu',batch=1)
    print('NCNN model:',result)
    print('Run warirak_ai.evaluate with this directory and the same held-out test data before deploying. Measure speed and temperature on the actual Pi.')

if __name__=='__main__':main()
