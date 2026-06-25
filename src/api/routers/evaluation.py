from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Body
from sqlalchemy.orm import Session
from typing import List, Optional, Any, Dict
from pydantic import BaseModel
import json
import os

from src.database.sql_session import get_db
from src.database.models import EvaluationTask, EvaluationResult, User, KnowledgeBase, GeneratedQAPair, KnowledgeDocument, EvaluationDatasetItem
from src.api.dependencies import get_current_user
from src.services.evaluator import RAGEvaluator
from src.llm.llm_client import LLMClient
from src.services.rag_service import RAGService
from src.services.qa_generator import qa_generator
import random
import math
import shutil
from fastapi import File, UploadFile

router = APIRouter()
llm_client = LLMClient()
evaluator = RAGEvaluator(llm_client)
rag_service = RAGService()

class EvalConfig(BaseModel):
    kb_id: Optional[int] = None
    num_questions: int = 10
    doc_ids: Optional[List[int]] = None
    mode: str = "kb" # "kb" or "doc"
    # Ratios for single_hop, multi_hop, error
    ratios: Dict[str, float] = {"single_hop": 0.7, "multi_hop": 0.2, "error": 0.1}
    num_docs: int = 5 # For KB mode, how many docs to sample
    is_custom_upload: bool = False

class EvalTaskOut(BaseModel):
    id: int
    name: str
    status: int
    created_at: Any
    completed_count: Optional[int] = 0
    total_count: Optional[int] = 0
    dataset_path: Optional[str]
    is_custom_dataset: bool
    
    class Config:
        from_attributes = True

class DatasetItemOut(BaseModel):
    id: int
    question: str
    ground_truth: str
    qa_type: str
    
    class Config:
        from_attributes = True

class DatasetItemUpdate(BaseModel):
    question: str
    ground_truth: str
    qa_type: str

def generate_dataset_task(task_id: int, db_session_factory):
    db = db_session_factory()
    try:
        task = db.query(EvaluationTask).filter(EvaluationTask.id == task_id).first()
        if not task: return
        
        config = task.config
        kb_id = task.kb_id
        num_questions = config.get("num_questions", 10)
        mode = config.get("mode", "kb")
        ratios = config.get("ratios", {"single_hop": 0.7, "multi_hop": 0.2, "error": 0.1})
        
        qa_dataset = []
        
        # Select documents
        if mode == "doc" and config.get("doc_ids"):
            docs = db.query(KnowledgeDocument).filter(KnowledgeDocument.id.in_(config["doc_ids"])).all()
        elif kb_id:
            all_docs = db.query(KnowledgeDocument).filter(KnowledgeDocument.kb_id == kb_id).all()
            num_docs_to_sample = min(len(all_docs), config.get("num_docs", 5))
            docs = random.sample(all_docs, num_docs_to_sample) if all_docs else []
        else:
            docs = []
            
        if not docs:
            task.status = 3
            task.error_msg = "No documents found" # This column doesn't exist on Task yet, assume added or handle error
            # Actually I added error_msg to Result, not Task. 
            # Let's just set status 3.
            db.commit()
            return

        # Generate QA Pairs
        targets = { k: math.ceil(num_questions * v) for k, v in ratios.items() }
        current_total = sum(targets.values())
        if current_total > num_questions:
            targets["single_hop"] -= (current_total - num_questions)
            
        def get_doc_text(doc):
            chunks = db.query(DocumentChunk).filter(DocumentChunk.doc_id == doc.id).limit(5).all()
            if chunks: return "\n".join([c.content for c in chunks])
            return f"Document content for {doc.filename}" 
            
        from src.database.models import DocumentChunk
        
        for qa_type, count in targets.items():
            if count <= 0: continue
            pairs_needed = count
            retries = 0
            while pairs_needed > 0 and retries < 3:
                doc = random.choice(docs)
                text = get_doc_text(doc)
                batch_size = min(pairs_needed, 5) 
                try:
                    new_pairs = qa_generator.generate_qa_pairs(text, batch_size, qa_type)
                    for p in new_pairs:
                        item = EvaluationDatasetItem(
                            task_id=task.id,
                            question=p["question"],
                            ground_truth=p["answer"],
                            qa_type=qa_type,
                            doc_id=doc.id
                        )
                        db.add(item)
                        pairs_needed -= 1
                        if pairs_needed <= 0: break
                except Exception as e:
                    print(f"QA Gen Error: {e}")
                retries += 1
        
        db.commit()
        
        # Count total
        count = db.query(EvaluationDatasetItem).filter(EvaluationDatasetItem.task_id == task.id).count()
        task.total_count = count
        task.status = 4 # DatasetGenerated
        db.commit()
        
    except Exception as e:
        print(f"Dataset Gen Failed: {e}")
        task.status = 3
        db.commit()
    finally:
        db.close()

def run_evaluation_execution(task_id: int, db_session_factory):
    db = db_session_factory()
    try:
        task = db.query(EvaluationTask).filter(EvaluationTask.id == task_id).first()
        if not task: return
        
        task.status = 1 # Running
        db.commit()
        
        # Fetch Dataset
        items = db.query(EvaluationDatasetItem).filter(EvaluationDatasetItem.task_id == task_id).all()
        kb_id = task.kb_id # Might be None for custom upload? No, RAG needs KB usually. 
        # If custom upload, maybe KB is optional? 
        # But RAGService.query needs kb_ids to retrieve from.
        # If task.kb_id is None, we assume General Chat or we need config.
        
        results = []
        completed = 0
        
        import time
        import numpy as np
        
        latencies = []
        first_tokens = []
        
        for item in items:
            error_msg = None
            rag_result = {}
            eval_res = {}
            first_token_latency = 0.0
            total_latency = 0.0
            
            try:
                # Run RAG
                rag_result = rag_service.query(item.question, top_k=5, kb_ids=[kb_id] if kb_id else None)
                
                # Evaluate
                eval_res = evaluator.evaluate(
                    query=item.question,
                    answer=rag_result["answer"],
                    source_documents=rag_result["source_documents"],
                    ground_truth=item.ground_truth
                )
                
                rag_metrics = rag_result.get("metrics", {})
                first_token_latency = rag_metrics.get("first_token_latency", 0.0)
                total_latency = rag_metrics.get("total_latency", 0.0)
                
                if total_latency > 0: latencies.append(total_latency)
                if first_token_latency > 0: first_tokens.append(first_token_latency)
                
            except Exception as e:
                error_msg = str(e)
                print(f"Error processing QA {item.id}: {e}")
            
            # Save Result
            res_entry = EvaluationResult(
                task_id=task.id,
                question=item.question,
                ground_truth=item.ground_truth,
                generated_answer=rag_result.get("answer"),
                metrics={
                    **(eval_res.get("scores", {}) if eval_res else {}),
                    "first_token_latency": first_token_latency,
                    "total_latency": total_latency,
                    "qa_type": item.qa_type
                },
                latency=total_latency,
                error_msg=error_msg
            )
            db.add(res_entry)
            
            if not error_msg:
                # Add to results for report
                eval_res["metrics"] = {
                    "first_token_latency": first_token_latency,
                    "total_latency": total_latency
                }
                eval_res["qa_type"] = item.qa_type
                results.append(eval_res)
            
            completed += 1
            task.completed_count = completed
            db.commit()
            
        # Generate Report with percentiles
        report = evaluator.generate_summary_report(results)
        
        # Append Percentiles
        if latencies:
            latencies.sort()
            percentiles = [50, 60, 70, 80, 90, 95]
            p_text = "\n## Latency Percentiles\n\n| Percentile | Latency (s) |\n|---|---|\n"
            for p in percentiles:
                val = np.percentile(latencies, p)
                p_text += f"| P{p} | {val:.2f} |\n"
            report += p_text
            
        report_path = f"data/reports/eval_{task.id}.md"
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report)
            
        task.report_path = report_path
        task.status = 2 # Completed
        db.commit()
        
    except Exception as e:
        print(f"Evaluation failed: {e}")
        import traceback
        task.status = 3
        db.commit()
    finally:
        db.close()

from src.database.sql_session import SessionLocal

@router.post("/generate", response_model=EvalTaskOut)
def generate_evaluation_dataset(
    config: EvalConfig,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # If not custom upload, check KB
    if not config.is_custom_upload:
        kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == config.kb_id).first()
        if not kb: raise HTTPException(status_code=404, detail="KB not found")
        if kb.owner_id != current_user.id: raise HTTPException(status_code=403, detail="Not authorized")
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = f"Eval-{kb.name}-{config.num_questions}-{timestamp}"
    else:
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = f"Eval-Custom-{config.num_questions}-{timestamp}"

    task = EvaluationTask(
        name=name,
        kb_id=config.kb_id,
        config=config.dict(),
        status=0, # Pending
        is_custom_dataset=config.is_custom_upload
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    
    if not config.is_custom_upload:
        background_tasks.add_task(generate_dataset_task, task.id, SessionLocal)
    else:
        # If custom upload, we wait for file upload to populate dataset
        # Status remains 0 until file is uploaded and processed
        pass
    
    return task

@router.post("/{task_id}/upload-dataset")
async def upload_evaluation_dataset(
    task_id: int,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    task = db.query(EvaluationTask).filter(EvaluationTask.id == task_id).first()
    if not task: raise HTTPException(status_code=404, detail="Task not found")
    
    # Process file (JSON/CSV)
    # Expected format: [{"question": "...", "ground_truth": "...", "qa_type": "..."}]
    try:
        content = await file.read()
        import pandas as pd
        import io
        
        items = []
        if file.filename.endswith('.json'):
            data = json.loads(content)
            for d in data:
                items.append(d)
        elif file.filename.endswith('.csv') or file.filename.endswith('.xlsx'):
            df = pd.read_csv(io.BytesIO(content)) if file.filename.endswith('.csv') else pd.read_excel(io.BytesIO(content))
            for _, row in df.iterrows():
                items.append({
                    "question": row.get("question"),
                    "ground_truth": row.get("answer") or row.get("ground_truth"),
                    "qa_type": row.get("type", "single_hop")
                })
        
        for item in items:
            db_item = EvaluationDatasetItem(
                task_id=task.id,
                question=item.get("question", ""),
                ground_truth=item.get("ground_truth", ""),
                qa_type=item.get("qa_type", "single_hop")
            )
            db.add(db_item)
            
        task.total_count = len(items)
        task.status = 4 # DatasetGenerated (Ready to review/run)
        db.commit()
        
        return {"message": f"Uploaded {len(items)} items"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid file: {e}")

@router.post("/{task_id}/run")
def run_evaluation(
    task_id: int,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    task = db.query(EvaluationTask).filter(EvaluationTask.id == task_id).first()
    if not task: raise HTTPException(status_code=404, detail="Task not found")
    
    if task.status != 4: # Must be generated/ready
        raise HTTPException(status_code=400, detail="Dataset not ready")
        
    background_tasks.add_task(run_evaluation_execution, task.id, SessionLocal)
    return {"message": "Evaluation started"}

@router.get("/{task_id}/dataset", response_model=List[DatasetItemOut])
def get_dataset_items(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return db.query(EvaluationDatasetItem).filter(EvaluationDatasetItem.task_id == task_id).all()

@router.put("/dataset-items/{item_id}")
def update_dataset_item(
    item_id: int,
    item_in: DatasetItemUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    item = db.query(EvaluationDatasetItem).filter(EvaluationDatasetItem.id == item_id).first()
    if not item: raise HTTPException(status_code=404)
    
    item.question = item_in.question
    item.ground_truth = item_in.ground_truth
    item.qa_type = item_in.qa_type
    db.commit()
    return item

@router.delete("/dataset-items/{item_id}")
def delete_dataset_item(
    item_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    item = db.query(EvaluationDatasetItem).filter(EvaluationDatasetItem.id == item_id).first()
    if not item: raise HTTPException(status_code=404)
    db.delete(item)
    
    # Update total count in task
    task = db.query(EvaluationTask).filter(EvaluationTask.id == item.task_id).first()
    if task:
        task.total_count = max(0, task.total_count - 1)
        
    db.commit()
    return {"message": "Deleted"}

@router.delete("/tasks/batch-delete")
def batch_delete_tasks(
    task_ids: List[int] = Body(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    tasks = db.query(EvaluationTask).filter(EvaluationTask.id.in_(task_ids)).all()
    count = 0
    for task in tasks:
        # Check permission (via KB or generic owner check if added to Task)
        # For now, assume open or check KB ownership if KB exists
        should_delete = False
        if task.kb_id:
            kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == task.kb_id).first()
            if kb and kb.owner_id == current_user.id:
                should_delete = True
        else:
            # Custom task, assume allow delete for now (or check creator if field exists)
            should_delete = True
            
        if should_delete:
            # Explicitly delete related records to avoid foreign key constraints
            db.query(EvaluationResult).filter(EvaluationResult.task_id == task.id).delete()
            db.query(EvaluationDatasetItem).filter(EvaluationDatasetItem.task_id == task.id).delete()
            db.delete(task)
            count += 1
            
    db.commit()
    return {"message": f"Deleted {count} tasks"}

@router.get("/tasks", response_model=List[EvalTaskOut])
def list_evaluation_tasks(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # In a real system, we might filter by user or KB ownership
    # For now, return all tasks for KBs owned by user
    # tasks = db.query(EvaluationTask).join(KnowledgeBase).filter(KnowledgeBase.owner_id == current_user.id).all()
    # But EvaluationTask only has kb_id.
    
    tasks = db.query(EvaluationTask).join(KnowledgeBase, EvaluationTask.kb_id == KnowledgeBase.id).filter(KnowledgeBase.owner_id == current_user.id).order_by(EvaluationTask.created_at.desc()).all()
    return tasks

@router.get("/{task_id}", response_model=EvalTaskOut)
def get_evaluation_status(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    task = db.query(EvaluationTask).filter(EvaluationTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task

@router.get("/{task_id}/report")
def get_evaluation_report(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    task = db.query(EvaluationTask).filter(EvaluationTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
        
    if not task.report_path or not os.path.exists(task.report_path):
        raise HTTPException(status_code=404, detail="Report not found")
        
    with open(task.report_path, "r", encoding="utf-8") as f:
        content = f.read()
        
    return {"content": content}
