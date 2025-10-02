"""
Base Parser - Abstract class for all resume format parsers.
"""

from abc import ABC, abstractmethod
from typing import Optional, List, Dict
from datetime import date
from pydantic import BaseModel, Field
import logging

logger = logging.getLogger(__name__)


# Data Models

class ContactInfo(BaseModel):
    """Contact information extracted from resume."""
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    linkedin: Optional[str] = None
    github: Optional[str] = None
    website: Optional[str] = None
    location: Optional[str] = None


class Experience(BaseModel):
    """Work experience entry."""
    title: str
    company: str
    location: Optional[str] = None
    start_date: Optional[str] = None  # Store as string for flexibility
    end_date: Optional[str] = None
    current: bool = False
    description: List[str] = Field(default_factory=list)
    technologies: List[str] = Field(default_factory=list)


class Education(BaseModel):
    """Education entry."""
    degree: str
    institution: str
    location: Optional[str] = None
    graduation_date: Optional[str] = None
    gpa: Optional[str] = None
    honors: List[str] = Field(default_factory=list)
    courses: List[str] = Field(default_factory=list)


class Project(BaseModel):
    """Project entry."""
    name: str
    description: str
    technologies: List[str] = Field(default_factory=list)
    url: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class Certification(BaseModel):
    """Certification entry."""
    name: str
    issuer: str
    date: Optional[str] = None
    expiry_date: Optional[str] = None
    credential_id: Optional[str] = None
    url: Optional[str] = None


class Language(BaseModel):
    """Language proficiency."""
    language: str
    proficiency: Optional[str] = None  # e.g., "Native", "Fluent", "Professional"


class Publication(BaseModel):
    """Publication or paper."""
    title: str
    authors: List[str] = Field(default_factory=list)
    venue: Optional[str] = None
    date: Optional[str] = None
    url: Optional[str] = None


class ParsedResume(BaseModel):
    """Complete structured resume data."""
    
    # Personal Information
    contact: ContactInfo = Field(default_factory=ContactInfo)
    
    # Professional Summary
    summary: Optional[str] = None
    objective: Optional[str] = None
    
    # Experience
    experience: List[Experience] = Field(default_factory=list)
    
    # Education
    education: List[Education] = Field(default_factory=list)
    
    # Skills
    skills: List[str] = Field(default_factory=list)
    skills_categorized: Dict[str, List[str]] = Field(default_factory=dict)
    
    # Additional Sections
    projects: List[Project] = Field(default_factory=list)
    certifications: List[Certification] = Field(default_factory=list)
    languages: List[Language] = Field(default_factory=list)
    publications: List[Publication] = Field(default_factory=list)
    
    # Miscellaneous
    awards: List[str] = Field(default_factory=list)
    volunteer: List[Dict] = Field(default_factory=list)
    interests: List[str] = Field(default_factory=list)
    references: List[Dict] = Field(default_factory=list)
    
    # Metadata
    metadata: Dict = Field(default_factory=dict)
    raw_text: Optional[str] = None  # Store original text for reference
    
    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return self.model_dump()
    
    def is_empty(self) -> bool:
        """Check if parsed resume is empty."""
        return not any([
            self.contact.name,
            self.contact.email,
            self.summary,
            self.experience,
            self.education,
            self.skills
        ])


class AbstractParser(ABC):
    """Abstract base class for all resume format parsers."""
    
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
    
    @abstractmethod
    async def parse(self, file_content: bytes, filename: str = "") -> ParsedResume:
        """
        Parse file content and extract structured resume data.
        
        Args:
            file_content: Raw bytes of the file
            filename: Optional filename for context
            
        Returns:
            ParsedResume: Structured resume data
            
        Raises:
            ValueError: If file cannot be parsed
            ParsingError: If parsing fails
        """
        pass
    
    @abstractmethod
    def validate(self, file_content: bytes) -> tuple[bool, Optional[str]]:
        """
        Validate if file can be parsed by this parser.
        
        Args:
            file_content: Raw bytes of the file
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        pass
    
    def extract_metadata(self, file_content: bytes, filename: str = "") -> Dict:
        """
        Extract file metadata.
        
        Args:
            file_content: Raw bytes of the file
            filename: Optional filename
            
        Returns:
            Dictionary of metadata
        """
        return {
            "filename": filename,
            "file_size": len(file_content),
            "parser": self.__class__.__name__
        }
    
    def post_process(self, parsed_resume: ParsedResume) -> ParsedResume:
        """
        Post-process parsed resume data.
        Clean up, normalize, and enhance extracted data.
        
        Args:
            parsed_resume: Initially parsed resume
            
        Returns:
            Enhanced ParsedResume
        """
        # Default implementation does basic cleanup
        
        # Remove empty experiences
        parsed_resume.experience = [exp for exp in parsed_resume.experience if exp.title or exp.company]
        
        # Remove empty education entries
        parsed_resume.education = [edu for edu in parsed_resume.education if edu.degree or edu.institution]
        
        # Remove duplicate skills
        if parsed_resume.skills:
            parsed_resume.skills = list(set(parsed_resume.skills))
        
        # Sort experiences by date (most recent first) if dates are available
        # This is a basic sort - can be enhanced
        
        return parsed_resume
    
    def get_confidence_score(self, parsed_resume: ParsedResume) -> float:
        """
        Calculate confidence score for parsed data (0.0 to 1.0).
        
        Args:
            parsed_resume: Parsed resume data
            
        Returns:
            Confidence score
        """
        score = 0.0
        max_score = 0.0
        
        # Contact info (30 points)
        max_score += 30
        if parsed_resume.contact.name:
            score += 15
        if parsed_resume.contact.email:
            score += 10
        if parsed_resume.contact.phone:
            score += 5
        
        # Experience (25 points)
        max_score += 25
        if parsed_resume.experience:
            score += min(25, len(parsed_resume.experience) * 5)
        
        # Education (20 points)
        max_score += 20
        if parsed_resume.education:
            score += min(20, len(parsed_resume.education) * 10)
        
        # Skills (15 points)
        max_score += 15
        if parsed_resume.skills:
            score += min(15, len(parsed_resume.skills))
        
        # Summary (10 points)
        max_score += 10
        if parsed_resume.summary:
            score += 10
        
        return score / max_score if max_score > 0 else 0.0


class ParsingError(Exception):
    """Custom exception for parsing errors."""
    pass

