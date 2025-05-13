from fastapi import FastAPI, HTTPException, Depends, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Any
from sqlalchemy import create_engine, Column, Integer, String, Text, ForeignKey, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from sqlalchemy.types import JSON as SQLAlchemyJSON
import datetime
import json
from fastapi.responses import JSONResponse

DATABASE_URL = "sqlite:///./surveys.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# SQLAlchemy Models
class Survey(Base):
    __tablename__ = "surveys"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    questions = Column(Text, nullable=False)  # Store as JSON string
    correct_answers = Column(Text, nullable=True)  # Store as JSON string
    responses = relationship("Response", back_populates="survey")

class Response(Base):
    __tablename__ = "responses"
    id = Column(Integer, primary_key=True, index=True)
    survey_id = Column(Integer, ForeignKey("surveys.id"))
    answers = Column(Text, nullable=False)  # Store as JSON string
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    student_name = Column(String, nullable=True)
    survey = relationship("Survey", back_populates="responses")

Base.metadata.create_all(bind=engine)

# Pydantic Schemas
class Question(BaseModel):
    text: str
    type: str  # e.g., 'text', 'radio', 'checkbox'
    options: Optional[List[str]] = None

class SurveyCreate(BaseModel):
    title: str
    description: Optional[str] = None
    questions: List[Question]
    correct_answers: Optional[Any] = None

class SurveyOut(BaseModel):
    id: int
    title: str
    description: Optional[str]
    questions: List[Question]
    correct_answers: Optional[Any] = None
    class Config:
        orm_mode = True

class ResponseCreate(BaseModel):
    answers: Any  # Should match the questions structure
    student_name: Optional[str] = None

class ResponseOut(BaseModel):
    id: int
    survey_id: int
    answers: Any
    timestamp: datetime.datetime
    student_name: Optional[str] = None
    class Config:
        orm_mode = True

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Endpoints
@app.post("/surveys/", response_model=SurveyOut)
def create_survey(survey: SurveyCreate, db: Session = Depends(get_db)):
    db_survey = Survey(
        title=survey.title,
        description=survey.description,
        questions=json.dumps([q.dict() for q in survey.questions]),
        correct_answers=json.dumps(survey.correct_answers) if survey.correct_answers is not None else None
    )
    db.add(db_survey)
    db.commit()
    db.refresh(db_survey)
    return SurveyOut(
        id=db_survey.id,
        title=db_survey.title,
        description=db_survey.description,
        questions=[Question(**q) for q in json.loads(db_survey.questions)],
        correct_answers=json.loads(db_survey.correct_answers) if db_survey.correct_answers else None
    )

@app.get("/surveys/", response_model=List[SurveyOut])
def list_surveys(db: Session = Depends(get_db)):
    surveys = db.query(Survey).all()
    return [
        SurveyOut(
            id=s.id,
            title=s.title,
            description=s.description,
            questions=[Question(**q) for q in json.loads(s.questions)],
            correct_answers=json.loads(s.correct_answers) if s.correct_answers else None
        ) for s in surveys
    ]

@app.get("/surveys/{survey_id}", response_model=SurveyOut)
def get_survey(survey_id: int, db: Session = Depends(get_db)):
    survey = db.query(Survey).filter(Survey.id == survey_id).first()
    if not survey:
        raise HTTPException(status_code=404, detail="Survey not found")
    return SurveyOut(
        id=survey.id,
        title=survey.title,
        description=survey.description,
        questions=[Question(**q) for q in json.loads(survey.questions)],
        correct_answers=json.loads(survey.correct_answers) if survey.correct_answers else None
    )

@app.post("/surveys/{survey_id}/responses")
def submit_response(survey_id: int, response: ResponseCreate, db: Session = Depends(get_db)):
    survey = db.query(Survey).filter(Survey.id == survey_id).first()
    if not survey:
        raise HTTPException(status_code=404, detail="Survey not found")
    db_response = Response(
        survey_id=survey_id,
        answers=json.dumps(response.answers),
        student_name=response.student_name
    )
    db.add(db_response)
    db.commit()
    db.refresh(db_response)
    # Score calculation
    score = None
    total = None
    if survey.correct_answers:
        correct = json.loads(survey.correct_answers)
        user = response.answers
        score = 0
        total = 0
        for k, v in correct.items():
            total += 1
            if isinstance(v, list):
                # For checkbox, compare as sets
                if set(user.get(k, [])) == set(v):
                    score += 1
            else:
                if user.get(k) == v:
                    score += 1
    return JSONResponse({
        "id": db_response.id,
        "survey_id": db_response.survey_id,
        "answers": json.loads(db_response.answers),
        "timestamp": db_response.timestamp.isoformat(),
        "student_name": db_response.student_name,
        "score": score,
        "total": total
    })

@app.delete("/surveys/{survey_id}", response_model=dict)
def delete_survey(survey_id: int, db: Session = Depends(get_db)):
    survey = db.query(Survey).filter(Survey.id == survey_id).first()
    if not survey:
        raise HTTPException(status_code=404, detail="Survey not found")
    db.delete(survey)
    db.commit()
    return {"detail": "Survey deleted"}

@app.put("/surveys/{survey_id}", response_model=SurveyOut)
def update_survey(survey_id: int, survey_update: SurveyCreate, db: Session = Depends(get_db)):
    survey = db.query(Survey).filter(Survey.id == survey_id).first()
    if not survey:
        raise HTTPException(status_code=404, detail="Survey not found")
    survey.title = survey_update.title
    survey.description = survey_update.description
    survey.questions = json.dumps([q.dict() for q in survey_update.questions])
    db.commit()
    db.refresh(survey)
    return SurveyOut(
        id=survey.id,
        title=survey.title,
        description=survey.description,
        questions=[Question(**q) for q in json.loads(survey.questions)]
    )

@app.get("/surveys/{survey_id}/responses", response_model=List[ResponseOut])
def list_responses(survey_id: int, db: Session = Depends(get_db)):
    responses = db.query(Response).filter(Response.survey_id == survey_id).all()
    return [
        ResponseOut(
            id=r.id,
            survey_id=r.survey_id,
            answers=json.loads(r.answers),
            timestamp=r.timestamp,
            student_name=r.student_name
        ) for r in responses
    ] 