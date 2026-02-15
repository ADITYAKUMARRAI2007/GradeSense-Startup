#!/usr/bin/env python3
from dotenv import load_dotenv
load_dotenv()
import asyncio
from app.database import db

async def check():
    sub = await db.submissions.find_one({'submission_id': 'sub_ca7d14f6'})
    
    print(f"Student: {sub['student_name']}")
    print(f"Exam: {sub['exam_id']}")
    print(f"Total score: {sub.get('total_score')}")
    print(f"\nQuestion Scores:")
    
    total_anns = 0
    line_id_anns = 0
    
    for qs in sub.get('question_scores', [])[:12]:
        q_num = qs['question_number']
        marks = qs['obtained_marks']
        anns = qs.get('annotations', [])
        total_anns += len(anns)
        
        print(f"\n  Q{q_num}: {marks} marks, {len(anns)} annotations")
        
        for idx, ann in enumerate(anns[:5], 1):
            line_ref = ''
            if ann.get('line_id'):
                line_ref = f"LineID={ann['line_id']}"
                line_id_anns += 1
            elif ann.get('line_id_start') or ann.get('line_id_end'):
                line_ref = f"Lines={ann.get('line_id_start')} to {ann.get('line_id_end')}"
                line_id_anns += 1
            else:
                anchor = ann.get('anchor_text', '')[:30]
                line_ref = f"Anchor={anchor}"
            
            ann_type = ann.get('type', 'UNKNOWN')
            print(f"    {idx}. {ann_type} | {line_ref}")
    
    print(f"\n{'='*70}")
    print(f"SUMMARY:")
    print(f"  Total annotations: {total_anns}")
    print(f"  Line-ID based: {line_id_anns} ({line_id_anns/max(total_anns, 1)*100:.1f}%)")
    print(f"  Anchor-based: {total_anns - line_id_anns}")
    print(f"{'='*70}")

asyncio.run(check())
