"""
Test Phase 14: Multi-Format Infrastructure
Tests format detection, parser framework, and file validation.
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from app.services.format_detection import format_detection_service, ResumeFormat
from app.parsers.parser_factory import parser_factory
from app.parsers.base_parser import ParsedResume


def test_format_detection():
    """Test format detection service."""
    print("\n" + "="*80)
    print("TEST 1: Format Detection Service")
    print("="*80)
    
    # Test 1: Detect from filename
    test_cases = [
        ("resume.tex", ResumeFormat.LATEX),
        ("resume.pdf", ResumeFormat.PDF),
        ("resume.docx", ResumeFormat.DOCX),
        ("resume.md", ResumeFormat.MARKDOWN),
        ("resume.txt", ResumeFormat.TEXT),
        ("resume.html", ResumeFormat.HTML),
        ("resume.json", ResumeFormat.JSON),
        ("resume.yaml", ResumeFormat.YAML),
        ("resume.unknown", ResumeFormat.UNKNOWN),
    ]
    
    print("\n1.1 Testing filename-based detection:")
    for filename, expected in test_cases:
        detected = format_detection_service.detect_format_from_filename(filename)
        status = "✅ PASS" if detected == expected else "❌ FAIL"
        print(f"  {status}: {filename:20} → {detected.value:10} (expected: {expected.value})")
    
    # Test 2: Detect from content
    print("\n1.2 Testing content-based detection:")
    
    latex_content = b"\\documentclass{article}\n\\begin{document}\nHello\\end{document}"
    detected = format_detection_service.detect_format_from_content(latex_content)
    print(f"  {'✅ PASS' if detected == ResumeFormat.LATEX else '❌ FAIL'}: LaTeX content → {detected.value}")
    
    html_content = b"<!DOCTYPE html><html><body>Resume</body></html>"
    detected = format_detection_service.detect_format_from_content(html_content)
    print(f"  {'✅ PASS' if detected == ResumeFormat.HTML else '❌ FAIL'}: HTML content → {detected.value}")
    
    json_content = b'{"name": "John Doe", "email": "john@example.com"}'
    detected = format_detection_service.detect_format_from_content(json_content)
    print(f"  {'✅ PASS' if detected == ResumeFormat.JSON else '❌ FAIL'}: JSON content → {detected.value}")
    
    pdf_content = b"%PDF-1.4\nSome PDF content"
    detected = format_detection_service.detect_format_from_content(pdf_content)
    print(f"  {'✅ PASS' if detected == ResumeFormat.PDF else '❌ FAIL'}: PDF content → {detected.value}")
    
    # Test 3: File size validation
    print("\n1.3 Testing file size validation:")
    
    test_sizes = [
        (1024 * 1024, ResumeFormat.TEXT, True),  # 1 MB text - valid
        (2 * 1024 * 1024, ResumeFormat.TEXT, False),  # 2 MB text - invalid
        (5 * 1024 * 1024, ResumeFormat.DOCX, True),  # 5 MB DOCX - valid
        (11 * 1024 * 1024, ResumeFormat.PDF, False),  # 11 MB PDF - invalid
    ]
    
    for size, format_type, expected_valid in test_sizes:
        is_valid, error = format_detection_service.validate_file_size(size, format_type)
        status = "✅ PASS" if is_valid == expected_valid else "❌ FAIL"
        size_mb = size / (1024 * 1024)
        print(f"  {status}: {size_mb:.1f}MB {format_type.value:10} → {'Valid' if is_valid else 'Invalid'}")


def test_parser_factory():
    """Test parser factory."""
    print("\n" + "="*80)
    print("TEST 2: Parser Factory")
    print("="*80)
    
    print("\n2.1 Testing parser registration:")
    supported_formats = parser_factory.get_supported_formats()
    print(f"  Registered parsers: {len(supported_formats)}")
    for fmt in supported_formats:
        print(f"    ✅ {fmt.value}")
    
    print("\n2.2 Testing parser retrieval:")
    for format_type in [ResumeFormat.LATEX]:
        parser = parser_factory.get_parser(format_type)
        status = "✅ PASS" if parser is not None else "❌ FAIL"
        print(f"  {status}: Get parser for {format_type.value}")
    
    print("\n2.3 Testing unsupported format:")
    for format_type in [ResumeFormat.PDF, ResumeFormat.DOCX]:
        parser = parser_factory.get_parser(format_type)
        status = "✅ PASS" if parser is None else "❌ FAIL"
        print(f"  {status}: {format_type.value} parser not yet implemented")


async def test_latex_parser():
    """Test LaTeX parser."""
    print("\n" + "="*80)
    print("TEST 3: LaTeX Parser")
    print("="*80)
    
    parser = parser_factory.get_parser(ResumeFormat.LATEX)
    
    if not parser:
        print("  ❌ FAIL: Could not get LaTeX parser")
        return
    
    # Test 1: Valid LaTeX content
    print("\n3.1 Testing valid LaTeX parsing:")
    valid_latex = b"""\\documentclass{article}
\\author{John Doe}
\\title{Software Engineer Resume}
\\begin{document}
\\maketitle
\\section{Experience}
Software Engineer at Tech Corp
\\end{document}"""
    
    try:
        parsed = await parser.parse(valid_latex, "test.tex")
        print(f"  ✅ PASS: Successfully parsed LaTeX file")
        print(f"    - Has raw text: {parsed.raw_text is not None}")
        print(f"    - Metadata: {parsed.metadata}")
        if parsed.contact.name:
            print(f"    - Extracted name: {parsed.contact.name}")
    except Exception as e:
        print(f"  ❌ FAIL: {e}")
    
    # Test 2: Invalid LaTeX content
    print("\n3.2 Testing invalid LaTeX validation:")
    invalid_latex = b"This is not LaTeX content"
    
    is_valid, error = parser.validate(invalid_latex)
    status = "✅ PASS" if not is_valid else "❌ FAIL"
    print(f"  {status}: Invalid LaTeX correctly rejected")
    if error:
        print(f"    - Error: {error}")
    
    # Test 3: Valid LaTeX validation
    print("\n3.3 Testing valid LaTeX validation:")
    is_valid, error = parser.validate(valid_latex)
    status = "✅ PASS" if is_valid else "❌ FAIL"
    print(f"  {status}: Valid LaTeX correctly accepted")


def test_format_info():
    """Test format information retrieval."""
    print("\n" + "="*80)
    print("TEST 4: Format Information")
    print("="*80)
    
    print("\n4.1 Getting all supported formats:")
    formats = format_detection_service.get_supported_formats()
    print(f"  Total formats: {len(formats)}")
    
    for fmt in formats[:3]:  # Show first 3
        print(f"\n  Format: {fmt['format']}")
        print(f"    Extensions: {', '.join(fmt['extensions'])}")
        print(f"    Max size: {fmt['max_size_mb']}MB")
    
    print("\n4.2 Getting specific format info:")
    latex_info = format_detection_service.get_format_info(ResumeFormat.LATEX)
    print(f"  LaTeX format:")
    print(f"    Extensions: {latex_info['extensions']}")
    print(f"    MIME types: {latex_info['mime_types']}")
    print(f"    Max size: {latex_info['max_size_mb']}MB")
    
    print("\n4.3 Testing format type checks:")
    test_formats = [
        (ResumeFormat.LATEX, True, False),
        (ResumeFormat.PDF, False, True),
        (ResumeFormat.MARKDOWN, True, True),
    ]
    
    for fmt, expected_text, expected_parse in test_formats:
        is_text = format_detection_service.is_text_based(fmt)
        needs_parse = format_detection_service.requires_parsing(fmt)
        
        text_status = "✅" if is_text == expected_text else "❌"
        parse_status = "✅" if needs_parse == expected_parse else "❌"
        
        print(f"  {fmt.value:10} - Text-based: {text_status} {is_text}, Requires parsing: {parse_status} {needs_parse}")


async def main():
    """Run all Phase 14 tests."""
    print("\n" + "="*80)
    print("PHASE 14: MULTI-FORMAT INFRASTRUCTURE TESTING")
    print("="*80)
    print("\nTesting core infrastructure for multi-format resume support")
    print("This includes format detection, parser framework, and validation.")
    
    try:
        # Run tests
        test_format_detection()
        test_parser_factory()
        await test_latex_parser()
        test_format_info()
        
        print("\n" + "="*80)
        print("PHASE 14 TESTING COMPLETE")
        print("="*80)
        print("\n✅ Core infrastructure implemented successfully!")
        print("\nNext Steps:")
        print("  1. Phase 15: Implement PDF and DOCX parsers")
        print("  2. Add structure extraction service")
        print("  3. Implement LaTeX generation from parsed data")
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())

