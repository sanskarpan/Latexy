# 🏗️ Multi-Format Resume Processing Architecture

## **System Overview**

```
┌──────────────────────────────────────────────────────────────────────────┐
│                           CLIENT / FRONTEND                               │
│                                                                           │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐   │
│  │   LaTeX     │  │     PDF     │  │    DOCX     │  │  Markdown   │   │
│  │   Upload    │  │   Upload    │  │   Upload    │  │   Upload    │   │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘   │
│         │                │                │                │             │
│         └────────────────┴────────────────┴────────────────┘             │
│                                  │                                        │
└──────────────────────────────────┼────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                           API GATEWAY                                     │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  POST /formats/validate                                          │   │
│  │  POST /formats/detect                                            │   │
│  │  GET  /formats/supported                                         │   │
│  │  POST /api/compile (with format auto-detection)                 │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                  │                                        │
└──────────────────────────────────┼────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                    FORMAT DETECTION SERVICE                               │
│                                                                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                  │
│  │   Extension  │  │  MIME Type   │  │ Magic Bytes  │                  │
│  │   Detection  │  │  Detection   │  │  Detection   │                  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘                  │
│         │                 │                 │                            │
│         └─────────────────┴─────────────────┘                            │
│                           │                                               │
│                ┌──────────▼──────────┐                                   │
│                │  Format Identified  │                                   │
│                │  (ResumeFormat)     │                                   │
│                └──────────┬──────────┘                                   │
└───────────────────────────┼───────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                       PARSER FACTORY                                      │
│                                                                           │
│  ┌────────────────────────────────────────────────────────────────┐     │
│  │  Select appropriate parser based on format type                │     │
│  └────────────┬───────────────────────────────────────────────────┘     │
│               │                                                           │
│    ┌──────────┼──────────┬──────────┬──────────┬──────────┬──────────┐ │
│    ▼          ▼          ▼          ▼          ▼          ▼          ▼ │
│  ┌────┐   ┌─────┐   ┌──────┐   ┌────┐   ┌──────┐   ┌──────┐   ┌──────┐│
│  │LaTeX│  │ PDF │   │ DOCX │   │ MD │   │ TXT  │   │ HTML │   │JSON │││
│  │Parser│  │Parser│  │Parser│   │Parser│ │Parser│   │Parser│   │Parser│││
│  │ ✅  │   │ 🔄 │   │ 🔄  │   │ 🔄│   │ 🔄  │   │ 🔄  │   │ 🔄 │││
│  └──┬─┘   └──┬──┘   └──┬───┘   └──┬─┘   └──┬───┘   └──┬───┘   └──┬───┘│
└─────┼────────┼─────────┼──────────┼────────┼──────────┼──────────┼─────┘
      │        │         │          │        │          │          │
      └────────┴─────────┴──────────┴────────┴──────────┴──────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                    PARSED RESUME (Structured Data)                        │
│                                                                           │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  ParsedResume {                                                   │   │
│  │    contact: ContactInfo                                           │   │
│  │    summary: string                                                │   │
│  │    experience: List[Experience]                                   │   │
│  │    education: List[Education]                                     │   │
│  │    skills: List[string]                                           │   │
│  │    projects: List[Project]                                        │   │
│  │    certifications: List[Certification]                            │   │
│  │    ...                                                            │   │
│  │  }                                                                │   │
│  └──────────────┬───────────────────────────────────────────────────┘   │
└─────────────────┼────────────────────────────────────────────────────────┘
                  │
                  ▼
┌──────────────────────────────────────────────────────────────────────────┐
│            STRUCTURE EXTRACTION SERVICE (Phase 15-16)                     │
│                                                                           │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐                │
│  │   NER    │  │ Contact  │  │ Section  │  │   Date   │                │
│  │ (spaCy)  │  │Extraction│  │Detection │  │  Parsing │                │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘                │
│       └─────────────┴─────────────┴─────────────┘                        │
│                            │                                              │
│                ┌───────────▼───────────┐                                 │
│                │  Enhanced Resume Data │                                 │
│                └───────────┬───────────┘                                 │
└────────────────────────────┼──────────────────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                LATEX GENERATION SERVICE (Phase 18)                        │
│                                                                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                  │
│  │  Template    │  │   Content    │  │  Formatting  │                  │
│  │  Selection   │  │   Mapping    │  │  Application │                  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘                  │
│         └──────────────────┴──────────────────┘                          │
│                            │                                              │
│                ┌───────────▼───────────┐                                 │
│                │   LaTeX Document      │                                 │
│                └───────────┬───────────┘                                 │
└────────────────────────────┼──────────────────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                    EXISTING PIPELINE                                      │
│                                                                           │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐            │
│  │     LLM      │────▶│    LaTeX     │────▶│     PDF      │            │
│  │ Optimization │     │  Compilation │     │  Generation  │            │
│  │  (Optional)  │     │   Service    │     │              │            │
│  └──────────────┘     └──────────────┘     └──────┬───────┘            │
└─────────────────────────────────────────────────────┼─────────────────────┘
                                                      │
                                                      ▼
                                            ┌──────────────────┐
                                            │   Final PDF      │
                                            │   Resume         │
                                            └──────────────────┘
```

---

## **Data Flow Diagram**

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        INPUT FORMATS                                     │
└───┬──────────┬──────────┬──────────┬──────────┬──────────┬──────────┬──┘
    │          │          │          │          │          │          │
  .tex       .pdf      .docx       .md        .txt      .html      .json
    │          │          │          │          │          │          │
    └──────────┴──────────┴──────────┴──────────┴──────────┴──────────┘
                                  │
                                  ▼
                        ┌─────────────────┐
                        │ Format Detection│
                        │   Multi-Method  │
                        └────────┬────────┘
                                 │
                                 ▼
                        ┌─────────────────┐
                        │ Parser Selection│
                        │   via Factory   │
                        └────────┬────────┘
                                 │
               ┌─────────────────┼─────────────────┐
               ▼                 ▼                 ▼
        ┌───────────┐     ┌───────────┐    ┌───────────┐
        │  LaTeX    │     │  Binary   │    │   Text    │
        │ Passthrough│     │  Parsers  │    │  Parsers  │
        │           │     │(PDF,DOCX) │    │(MD,TXT,HTML)│
        └─────┬─────┘     └─────┬─────┘    └─────┬─────┘
              │                 │                 │
              └─────────────────┼─────────────────┘
                                │
                                ▼
                      ┌──────────────────┐
                      │  ParsedResume    │
                      │  (Structured)    │
                      └────────┬─────────┘
                               │
           ┌───────────────────┼───────────────────┐
           ▼                   ▼                   ▼
    ┌────────────┐      ┌────────────┐     ┌────────────┐
    │  Contact   │      │ Experience │     │ Education  │
    │   Info     │      │   List     │     │   List     │
    └────────────┘      └────────────┘     └────────────┘
           │                   │                   │
           └───────────────────┼───────────────────┘
                               │
                               ▼
                     ┌──────────────────┐
                     │ Structure Extract│
                     │    (NER, NLP)    │
                     └────────┬─────────┘
                              │
                              ▼
                     ┌──────────────────┐
                     │ LaTeX Generation │
                     │  + Templates     │
                     └────────┬─────────┘
                              │
                              ▼
                     ┌──────────────────┐
                     │  LLM Optimize    │
                     │   (Optional)     │
                     └────────┬─────────┘
                              │
                              ▼
                     ┌──────────────────┐
                     │LaTeX Compilation │
                     │   (Existing)     │
                     └────────┬─────────┘
                              │
                              ▼
                     ┌──────────────────┐
                     │   Final PDF      │
                     └──────────────────┘
```

---

## **Component Interaction Matrix**

| Component | Interacts With | Purpose |
|-----------|---------------|---------|
| **Format Detection** | API Layer | Identify file format |
| **Parser Factory** | Format Detection | Select appropriate parser |
| **Parsers** | Parser Factory | Parse specific formats |
| **ParsedResume** | All Parsers | Standardized data structure |
| **Structure Extractor** | ParsedResume | Enhance extracted data |
| **LaTeX Generator** | ParsedResume | Convert to LaTeX |
| **LLM Service** | LaTeX Content | Optimize resume |
| **Compilation** | LaTeX Content | Generate PDF |

---

## **File Type Processing Paths**

### **Path 1: LaTeX (Native) - IMPLEMENTED ✅**
```
.tex → Format Detection → LaTeX Parser → Raw LaTeX → Compilation → PDF
```

### **Path 2: PDF - PLANNED (Phase 15)**
```
.pdf → Format Detection → PDF Parser → Text Extraction → 
Structure Extract → LaTeX Generation → Compilation → PDF
```

### **Path 3: DOCX - PLANNED (Phase 15)**
```
.docx → Format Detection → DOCX Parser → Content Parse → 
Structure Extract → LaTeX Generation → Compilation → PDF
```

### **Path 4: Markdown - PLANNED (Phase 16)**
```
.md → Format Detection → Markdown Parser → Parse Sections → 
LaTeX Generation → Compilation → PDF
```

### **Path 5: Text - PLANNED (Phase 16)**
```
.txt → Format Detection → Text Parser → NLP Extract → 
Structure Extract → LaTeX Generation → Compilation → PDF
```

### **Path 6: JSON - PLANNED (Phase 17)**
```
.json → Format Detection → JSON Parser → Validate Schema → 
LaTeX Generation → Compilation → PDF
```

---

## **Error Handling Flow**

```
┌────────────────┐
│  File Upload   │
└───────┬────────┘
        │
        ▼
┌────────────────┐      ┌──────────────────┐
│ Format Detect  │─NO──▶│ Return Error:    │
│   Success?     │      │ "Unsupported     │
└───────┬────────┘      │  Format"         │
        │YES            └──────────────────┘
        ▼
┌────────────────┐      ┌──────────────────┐
│ Parser Exists? │─NO──▶│ Return Error:    │
│                │      │ "No Parser       │
└───────┬────────┘      │  Available"      │
        │YES            └──────────────────┘
        ▼
┌────────────────┐      ┌──────────────────┐
│ File Valid?    │─NO──▶│ Return Error:    │
│ (Size, Content)│      │ "Validation      │
└───────┬────────┘      │  Failed"         │
        │YES            └──────────────────┘
        ▼
┌────────────────┐      ┌──────────────────┐
│ Parse Success? │─NO──▶│ Return Error:    │
│                │      │ "Parse Error"    │
└───────┬────────┘      └──────────────────┘
        │YES
        ▼
┌────────────────┐
│ Return Parsed  │
│    Resume      │
└────────────────┘
```

---

## **Security Architecture**

```
┌──────────────────────────────────────────────────────────────┐
│                      SECURITY LAYERS                          │
├──────────────────────────────────────────────────────────────┤
│                                                               │
│  Layer 1: File Upload Validation                             │
│  ┌────────────────────────────────────────────────────┐      │
│  │ • File size limits (format-specific)               │      │
│  │ • Extension whitelist                              │      │
│  │ • MIME type verification                           │      │
│  └────────────────────────────────────────────────────┘      │
│                          │                                    │
│                          ▼                                    │
│  Layer 2: Content Validation                                 │
│  ┌────────────────────────────────────────────────────┐      │
│  │ • Magic byte verification                          │      │
│  │ • Structure validation                             │      │
│  │ • Encoding check (UTF-8)                           │      │
│  └────────────────────────────────────────────────────┘      │
│                          │                                    │
│                          ▼                                    │
│  Layer 3: Parsing Security                                   │
│  ┌────────────────────────────────────────────────────┐      │
│  │ • Sandboxed parsing (future)                       │      │
│  │ • Resource limits (memory, CPU)                    │      │
│  │ • Timeout protection                               │      │
│  └────────────────────────────────────────────────────┘      │
│                          │                                    │
│                          ▼                                    │
│  Layer 4: Rate Limiting                                      │
│  ┌────────────────────────────────────────────────────┐      │
│  │ • Per-user upload limits                           │      │
│  │ • IP-based throttling                              │      │
│  │ • Concurrent request limits                        │      │
│  └────────────────────────────────────────────────────┘      │
│                                                               │
└──────────────────────────────────────────────────────────────┘
```

---

## **Performance Optimization**

```
┌─────────────────────────────────────────────────────┐
│              OPTIMIZATION STRATEGIES                 │
├─────────────────────────────────────────────────────┤
│                                                      │
│  1. Format Detection Cache                          │
│     ┌────────────────────────────────────┐          │
│     │ Recent files → Cache results       │          │
│     │ TTL: 5 minutes                     │          │
│     └────────────────────────────────────┘          │
│                                                      │
│  2. Parser Instance Pooling                         │
│     ┌────────────────────────────────────┐          │
│     │ Reuse parser instances             │          │
│     │ Max pool size: 10                  │          │
│     └────────────────────────────────────┘          │
│                                                      │
│  3. Async Processing                                │
│     ┌────────────────────────────────────┐          │
│     │ All parsers use async/await        │          │
│     │ Non-blocking I/O                   │          │
│     └────────────────────────────────────┘          │
│                                                      │
│  4. Streaming for Large Files                       │
│     ┌────────────────────────────────────┐          │
│     │ Process in chunks                  │          │
│     │ Memory-efficient                   │          │
│     └────────────────────────────────────┘          │
│                                                      │
└─────────────────────────────────────────────────────┘
```

---

**Legend:**
- ✅ = Implemented (Phase 14)
- 🔄 = Planned (Phases 15-18)
- ⏳ = Future Enhancement

**Architecture Version:** 1.0  
**Last Updated:** $(date)


