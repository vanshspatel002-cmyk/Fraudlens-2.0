"""Extract and rasterize every controlled sample page; no application I/O."""
import argparse
import json
from pathlib import Path

import fitz
from PIL import Image, ImageDraw


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=Path(__file__).resolve().parents[2]/'docs/visual_review');args=parser.parse_args()
    renders=args.output/'.renders';renders.mkdir(exist_ok=True)
    screenshots=args.output/'screenshots';screenshots.mkdir(exist_ok=True)
    results=[];captured=set()
    labels=['Registration reading','Photographic coverage','Internal photograph reuse','External photograph matches','Shared identifiers','Earlier inspection link','Damage history','Capture metadata','Content credentials','Experimental synthetic image check','Experimental image editing check','Scene, time and place','Damage and claimed amount','Experimental baseline check','Garage billing pattern']
    wanted={'Internal photograph reuse':'check-image-reuse','Registration reading':'check-registration','Capture metadata':'check-metadata','Shared identifiers':'check-relationships','Garage billing pattern':'check-billing-pattern','Experimental synthetic image check':'check-experimental'}
    for pdf in sorted(args.output.glob('*.pdf')):
        doc=fitz.open(pdf);thumbs=[];issues=[]
        for index,page in enumerate(doc):
            assert page.get_text().strip(),(pdf,index,'empty page')
            for block in page.get_text('blocks'):
                if block[0]<-1 or block[1]<-1 or block[2]>page.rect.width+1 or block[3]>page.rect.height+1:issues.append({'page':index+1,'issue':'text outside page'})
            for info in page.get_image_info():
                box=fitz.Rect(info['bbox']);expected=info['width']/info['height']
                if abs(box.width/box.height-expected)>.02:issues.append({'page':index+1,'issue':'image aspect ratio changed'})
            image_path=renders/f'{pdf.stem}-page-{index+1}.png'
            page.get_pixmap(matrix=fitz.Matrix(1.5,1.5)).save(image_path)
            if index==0 and pdf.stem in {'claims-high','underwriting-medium'}:
                page.get_pixmap(matrix=fitz.Matrix(1.2,1.2),colorspace=fitz.csGRAY).save(screenshots/(pdf.stem+'-grayscale.png'))
            image=Image.open(image_path).convert('RGB');image.thumbnail((560,792))
            thumb=Image.new('RGB',(580,825),'#e8eeee');thumb.paste(image,((580-image.width)//2,12));ImageDraw.Draw(thumb).text((12,807),f'{pdf.stem} / page {index+1}',fill='#203941');thumbs.append(thumb)
            if pdf.stem=='claims-high':
                for label,name in wanted.items():
                    found=page.search_for(label)
                    if not found or name in captured:continue
                    top=found[0].y0-7
                    next_titles=[r.y0-5 for title in labels if title!=label for r in page.search_for(title) if r.y0>found[0].y0+15]
                    bottom=min(next_titles+[top+330,page.rect.height-45])
                    if bottom-top<65:continue
                    page.get_pixmap(matrix=fitz.Matrix(1.8,1.8),clip=fitz.Rect(40,top,page.rect.width-40,bottom)).save(screenshots/(name+'.png'))
                    captured.add(name)
            if pdf.stem=='claims-incomplete':
                found=page.search_for('Scene, time and place')
                if found and 'check-unavailable' not in captured:
                    page.get_pixmap(matrix=fitz.Matrix(1.8,1.8),clip=fitz.Rect(40,found[0].y0-7,page.rect.width-40,min(page.rect.height-45,found[0].y0+180))).save(screenshots/'check-unavailable.png')
                    captured.add('check-unavailable')
        sheet=Image.new('RGB',(1160,825*((len(thumbs)+1)//2)),'white')
        for index,image in enumerate(thumbs):sheet.paste(image,((index%2)*580,(index//2)*825))
        sheet.save(args.output/(pdf.stem+'-all-pages.png'))
        assert not issues,(pdf.name,issues)
        results.append({'file':pdf.name,'pages':len(doc),'all_pages_rendered':True,'text_and_image_bounds':'passed','image_aspect_ratios':'passed','first_page_label':next((line for line in doc[0].get_text().splitlines() if line.startswith(('Assessed risk','Assessment incomplete'))),'missing')})
    (args.output/'pdf-inspection.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    print(json.dumps(results,indent=2))


if __name__=='__main__':main()
