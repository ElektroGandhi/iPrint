"""The German and English READMEs must stay the same page in two languages: same sections, pictures, code and links."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
GERMAN, ENGLISH = (ROOT / "README.md").read_text(), (ROOT / "README.en.md").read_text()


def outline(text):
    """The shape of a page without its words."""
    shape = []
    for line in text.splitlines():
        if line.startswith("#"):
            shape.append(line.split(" ", 1)[0])
        elif line.startswith("```"):
            shape.append("```")
        elif line.startswith("|"):
            shape.append("|" * line.count("|"))
        elif re.match(r"\s*(- |\d+\. )", line):
            shape.append("item")
    return shape


def pictures(text):
    return [p for p in re.findall(r'src="([^"]+)"', text) if "shields.io" not in p]


def badges(text):
    return text.count("shields.io")


def links(text):
    """Targets of all links, except the one pointing at the other language."""
    found = re.findall(r'href="([^"]+)"', text) + re.findall(r"\]\(([^)]+)\)", text)
    return [t for t in found if t not in ("README.md", "README.en.md")]


def test_same_outline():
    assert outline(GERMAN) == outline(ENGLISH)


def test_same_pictures():
    assert pictures(GERMAN) == pictures(ENGLISH) and pictures(GERMAN)


def test_same_badges():
    assert badges(GERMAN) == badges(ENGLISH) > 0


def test_same_links():
    assert links(GERMAN) == links(ENGLISH) and links(GERMAN)


def test_each_links_to_the_other():
    assert 'href="README.en.md"' in GERMAN and 'href="README.md"' in ENGLISH


def test_every_local_link_and_picture_exists():
    for target in pictures(GERMAN) + links(GERMAN):
        if not target.startswith("http"):
            assert (ROOT / target).exists(), target
