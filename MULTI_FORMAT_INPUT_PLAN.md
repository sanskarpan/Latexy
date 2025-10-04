# Multi-Format Input Support - Implementation Plan

**Document Version:** 1.0  
**Created:** $(date)  
**Phases:** 14-18

---

## 🎯 **OVERVIEW**

Transform Latexy from a LaTeX-only platform to a **universal resume converter** that accepts multiple input formats and converts them to optimized, ATS-friendly LaTeX resumes.

### **Supported Input Formats**
1. **LaTeX (.tex)** - Native support (already implemented)
2. **PDF (.pdf)** - Extract text and structure
3. **Word Documents (.docx, .doc)** - Parse and convert
4. **Markdown (.md)** - Convert to LaTeX
5. **Plain Text (.txt)** - Parse and structure
6. **HTML/Web (.html)** - Extract and convert
7. **JSON/YAML** - Structured resume data
8. **LinkedIn Export** - Direct import

---

## 🏗️ **ARCHITECTURE OVERVIEW**

### **Processing Pipeline**
```
Input File → Format Detection → Parser → Structure Extractor → LaTeX Generator → Optimizer → PDF Output
     ↓              ↓               ↓            ↓                    ↓             ↓          ↓
  Multiple      Auto-detect    Format-      Resume         LaTeX         LLM      Final
  Formats       File Type      Specific     Sections       Template    Optimization  PDF
                              Parser       (Name, Edu,    Generation
                                          Skills, etc)
```

### **Component Architecture**
```
┌─────────────────────────────────────────────────────────────┐
│                    INPUT LAYER                              │
├─────────────────────────────────────────────────────────────┤
│  PDF  │  DOCX  │  MD  │  TXT  │  HTML  │  JSON  │  LaTeX    │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│              FORMAT DETECTION SERVICE                       │
│  - MIME type detection                                      │
│  - File extension validation                                │
│  - Content analysis                                         │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│              PARSER LAYER                                   │
│  - PDF Parser (PyPDF2, pdfplumber)                          │
│  - DOCX Parser (python-docx)                                │
│  - Markdown Parser (markdown-it-py)                         │
│  - Text Parser (NLP-based)                                  │
│  - HTML Parser (BeautifulSoup4)                             │
│  - JSON Parser (native)                                     │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│         STRUCTURE EXTRACTION SERVICE                        │
│  - Named Entity Recognition (NER)                           │
│  - Section Detection (Education, Experience, etc.)          │
│  - Contact Information Extraction                           │
│  - Date Parsing and Normalization                           │
│  - Skills Extraction                                        │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│         LATEX GENERATION SERVICE                            │
│  - Template Selection                                       │
│  - Content Mapping                                          │
│  - Formatting Application                                   │
│  - LaTeX Code Generation                                    │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│         OPTIMIZATION & OUTPUT                               │
│  - LLM Optimization (existing)                              │
│  - LaTeX Compilation (existing)                             │
│  - PDF Generation (existing)                                │
└─────────────────────────────────────────────────────────────┘
```

---

## 📋 **PHASE BREAKDOWN**

### **Phase 14: Core Multi-Format Infrastructure** (3 weeks)
**Purpose:** Build foundational infrastructure for format detection and parsing

#### **Week 1: Format Detection & Validation**
- File upload enhancement (support multiple formats)
- MIME type detection service
- File size and security validation
- Format compatibility checker

#### **Week 2: Parser Framework**
- Abstract parser interface
- Parser factory pattern
- Error handling and fallback
- Parser registry system

#### **Week 3: Testing & Integration**
- Unit tests for each parser
- Integration tests
- Error handling validation
- Performance benchmarking

**Deliverables:**
- `FormatDetectionService`
- `ParserFactory`
- `AbstractParser` base class
- File validation utilities
- Comprehensive tests

---

### **Phase 15: PDF & DOCX Support** (4 weeks)
**Purpose:** Implement parsers for the most common document formats

#### **Week 1: PDF Parser**
- **Libraries:** PyPDF2, pdfplumber, pdfminer.six
- Text extraction with layout preservation
- Table extraction
- Multi-column detection
- Image and logo handling

#### **Week 2: DOCX Parser**
- **Library:** python-docx
- Paragraph and heading extraction
- Table parsing
- Style and formatting detection
- Template detection

#### **Week 3: Structure Extraction**
- Section identification
- Contact information extraction
- Date parsing and normalization
- Skills and keywords extraction

#### **Week 4: Testing & Refinement**
- Test with various PDF formats
- Test with different Word templates
- Edge case handling
- Performance optimization

**Deliverables:**
- `PDFParser` class
- `DOCXParser` class
- `StructureExtractor` service
- Contact information extractor
- Date normalizer

---

### **Phase 16: Markdown, Text & HTML Support** (3 weeks)
**Purpose:** Support lightweight and web-based formats

#### **Week 1: Markdown Parser**
- **Library:** markdown-it-py, mistune
- Markdown to LaTeX conversion
- Custom resume markdown syntax
- Code block handling
- Link preservation

#### **Week 2: Plain Text Parser**
- **Library:** spaCy for NLP
- Intelligent section detection
- Named Entity Recognition (NER)
- Pattern matching for common formats
- Heuristic-based structuring

#### **Week 3: HTML Parser**
- **Library:** BeautifulSoup4, lxml
- Web resume extraction
- LinkedIn profile parsing
- Semantic HTML interpretation
- Style stripping and conversion

**Deliverables:**
- `MarkdownParser` class
- `TextParser` class
- `HTMLParser` class
- NER-based extraction
- Pattern matching engine

---

### **Phase 17: Structured Data & Advanced Formats** (2 weeks)
**Purpose:** Support structured data formats and advanced features

#### **Week 1: JSON/YAML Parser**
- JSON resume schema support
- YAML resume format
- Custom schema validation
- Field mapping configuration
- Data transformation

#### **Week 2: Advanced Features**
- LinkedIn export support
- Indeed profile import
- GitHub resume parsing
- Multi-file upload (images, docs)
- Resume merging capabilities

**Deliverables:**
- `JSONParser` class
- `YAMLParser` class
- Schema validator
- LinkedIn importer
- Multi-file handler

---

### **Phase 18: LaTeX Generation & Frontend Integration** (4 weeks)
**Purpose:** Complete the pipeline and integrate with frontend

#### **Week 1: LaTeX Template System**
- Dynamic template generation
- Section mapping engine
- Style configuration
- Custom formatting rules
- Template library expansion

#### **Week 2: Content Mapper**
- Field-to-LaTeX mapping
- Smart formatting decisions
- Date formatting
- List generation
- Special character handling

#### **Week 3: Frontend Integration**
- Multi-format file upload UI
- Format preview and validation
- Drag-and-drop interface
- Batch upload support
- Progress indicators

#### **Week 4: Testing & Polish**
- End-to-end testing all formats
- User acceptance testing
- Performance optimization
- Error messaging improvement
- Documentation

**Deliverables:**
- `LaTeXGenerator` service
- `ContentMapper` service
- Template library
- Frontend upload component
- Complete integration

---

## 🔧 **TECHNICAL SPECIFICATIONS**

### **Backend Services**

#### **1. Format Detection Service**
```python
class FormatDetectionService:
    """Detect and validate input file formats."""
    
    def detect_format(self, file: UploadFile) -> str:
        """Detect file format from MIME type and extension."""
        pass
    
    def validate_format(self, format: str) -> bool:
        """Validate if format is supported."""
        pass
    
    def get_parser(self, format: str) -> AbstractParser:
        """Get appropriate parser for format."""
        pass
```

#### **2. Abstract Parser Interface**
```python
class AbstractParser(ABC):
    """Base class for all format parsers."""
    
    @abstractmethod
    async def parse(self, file_content: bytes) -> ParsedResume:
        """Parse file content and extract structured data."""
        pass
    
    @abstractmethod
    def validate(self, file_content: bytes) -> bool:
        """Validate file can be parsed."""
        pass
    
    def extract_metadata(self, file_content: bytes) -> dict:
        """Extract file metadata."""
        pass
```

#### **3. Structure Extraction Service**
```python
class StructureExtractor:
    """Extract structured resume data from parsed content."""
    
    def extract_contact_info(self, text: str) -> ContactInfo:
        """Extract name, email, phone, address."""
        pass
    
    def extract_sections(self, text: str) -> List[Section]:
        """Identify and extract resume sections."""
        pass
    
    def extract_experience(self, section_text: str) -> List[Experience]:
        """Parse work experience."""
        pass
    
    def extract_education(self, section_text: str) -> List[Education]:
        """Parse education details."""
        pass
    
    def extract_skills(self, text: str) -> List[str]:
        """Extract skills and keywords."""
        pass
```

#### **4. LaTeX Generator Service**
```python
class LaTeXGenerator:
    """Generate LaTeX code from structured resume data."""
    
    def generate(self, resume_data: ParsedResume, template: str = "default") -> str:
        """Generate complete LaTeX document."""
        pass
    
    def select_template(self, resume_data: ParsedResume) -> str:
        """Auto-select best template."""
        pass
    
    def map_content(self, resume_data: ParsedResume) -> dict:
        """Map resume data to LaTeX sections."""
        pass
    
    def apply_formatting(self, content: dict) -> str:
        """Apply LaTeX formatting."""
        pass
```

### **Data Models**

```python
class ParsedResume(BaseModel):
    """Structured resume data."""
    contact: ContactInfo
    summary: Optional[str]
    experience: List[Experience]
    education: List[Education]
    skills: List[str]
    certifications: List[Certification]
    projects: List[Project]
    languages: List[Language]
    metadata: dict

class ContactInfo(BaseModel):
    name: str
    email: Optional[str]
    phone: Optional[str]
    address: Optional[str]
    linkedin: Optional[str]
    github: Optional[str]
    website: Optional[str]

class Experience(BaseModel):
    title: str
    company: str
    location: Optional[str]
    start_date: Optional[date]
    end_date: Optional[date]
    current: bool = False
    description: List[str]
    technologies: List[str]

class Education(BaseModel):
    degree: str
    institution: str
    location: Optional[str]
    graduation_date: Optional[date]
    gpa: Optional[float]
    honors: List[str]
```

---

## 🎨 **FRONTEND DESIGN**

### **File Upload Component**
```typescript
interface FileUploadProps {
  acceptedFormats: string[];
  maxFileSize: number;
  onUpload: (file: File) => void;
  onError: (error: string) => void;
}

const MultiFormatUpload: React.FC<FileUploadProps> = () => {
  // Drag-and-drop support
  // Format validation
  // Preview generation
  // Progress indicator
  // Multiple file support
}
```

### **Format Preview Component**
```typescript
interface FormatPreviewProps {
  file: File;
  parsedData: ParsedResume;
  format: string;
}

const FormatPreview: React.FC<FormatPreviewProps> = () => {
  // Show detected sections
  // Highlight extracted data
  // Allow manual corrections
  // Template selection
}
```

---

## 📦 **REQUIRED LIBRARIES**

### **Python (Backend)**
```txt
# PDF Processing
PyPDF2==3.0.1
pdfplumber==0.10.3
pdfminer.six==20221105

# DOCX Processing
python-docx==1.1.0
docx2txt==0.8

# Markdown Processing
markdown-it-py==3.0.0
mistune==3.0.2

# HTML Processing
beautifulsoup4==4.12.2
lxml==4.9.3

# Text Processing & NLP
spacy==3.7.2
en-core-web-sm  # spaCy model

# Structured Data
pyyaml==6.0.1
jsonschema==4.20.0

# Date Parsing
python-dateutil==2.8.2
```

### **TypeScript (Frontend)**
```json
{
  "dependencies": {
    "react-dropzone": "^14.2.3",
    "file-type": "^18.5.0",
    "@uppy/core": "^3.7.1",
    "@uppy/react": "^3.1.3",
    "react-pdf": "^7.5.1"
  }
}
```

---

## 🔒 **SECURITY CONSIDERATIONS**

### **File Upload Security**
1. **File Size Limits**
   - PDF: 10 MB max
   - DOCX: 5 MB max
   - Others: 2 MB max

2. **Format Validation**
   - Magic number verification
   - Extension whitelist
   - Content-type validation
   - Virus scanning integration

3. **Content Security**
   - Sanitize extracted text
   - Remove embedded scripts
   - Strip macros from DOCX
   - Validate LaTeX output

4. **Rate Limiting**
   - Per-user upload limits
   - Processing queue management
   - Resource throttling

---

## 📊 **SUCCESS METRICS**

### **Parsing Accuracy**
- PDF parsing: >95% accuracy
- DOCX parsing: >98% accuracy
- Markdown: >99% accuracy
- Text: >85% accuracy (due to variability)

### **Performance**
- PDF parsing: <5 seconds
- DOCX parsing: <3 seconds
- Markdown/Text: <1 second
- LaTeX generation: <2 seconds

### **User Experience**
- File upload success rate: >99%
- Format detection accuracy: >99%
- User satisfaction: >4.5/5
- Conversion accuracy: >90%

---

## 🧪 **TESTING STRATEGY**

### **Unit Tests**
- Each parser tested independently
- Edge cases for each format
- Error handling validation
- Performance benchmarks

### **Integration Tests**
- End-to-end format conversion
- Multi-step pipeline testing
- Error recovery testing
- Concurrent processing

### **Real-World Testing**
- Test with actual user resumes
- Various format variations
- Edge cases and corrupted files
- Performance under load

---

## 🚀 **ROLLOUT PLAN**

### **Phase 14 (Week 1-3)**
- Core infrastructure
- Format detection
- Parser framework

### **Phase 15 (Week 4-7)**
- PDF support (most requested)
- DOCX support (second most requested)
- Beta testing with users

### **Phase 16 (Week 8-10)**
- Markdown, Text, HTML
- Expand format support
- User feedback integration

### **Phase 17 (Week 11-12)**
- JSON/YAML support
- LinkedIn import
- Advanced features

### **Phase 18 (Week 13-16)**
- LaTeX generation refinement
- Frontend integration
- Complete testing
- Production launch

---

## 💡 **FUTURE ENHANCEMENTS**

### **Post-Phase 18**
1. **Image Recognition**
   - OCR for scanned PDFs
   - Logo extraction
   - Image-based resumes

2. **Video Resumes**
   - Video-to-text transcription
   - Key point extraction
   - Timeline generation

3. **Social Media Import**
   - Twitter/X profile import
   - Facebook work history
   - Instagram portfolio

4. **Batch Processing**
   - Multiple file uploads
   - Resume comparison
   - Bulk optimization

---

**Plan Created:** $(date)  
**Total Duration:** 16 weeks  
**Next Step:** Phase 14 Implementation

