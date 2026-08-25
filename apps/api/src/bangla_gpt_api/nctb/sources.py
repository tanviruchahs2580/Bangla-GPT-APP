"""Verified NCTB source inventory.

Recorded during discovery on 2026-08-25 against nctb.gov.bd:

- Landing page (master prompt primary source):
    https://nctb.gov.bd/pages/static-pages/695b98afc4774958d7b7044c
  Contains six artifacts/pages: প্রবিধানমালা, প্রাক-প্রাথমিক ২০১১,
  প্রাথমিক ২০১১, মাধ্যমিক (Secondary), উচ্চ মাধ্যমিক (Higher Secondary),
  প্রাথমিক শিক্ষাক্রম মূল্যায়ন.

- Secondary listing page:
    https://nctb.gov.bd/pages/files/6922db5b933eb65569e09a2c
  Section heading: "মাধ্যমিক স্তরের শিক্ষাক্রম(প্রকাশকাল -২০১২)"
  16 textbook PDFs hosted on the ministry object storage bucket.

- Higher-secondary listing page:
    https://nctb.gov.bd/pages/files/6922dbc6933eb65569e0c702
  Section heading: "উচ্চ মাধ্যমিক স্তরের শিক্ষাক্রম"
  32 textbook PDFs hosted on the same bucket.

Class coverage of the two listing pages: Secondary = classes 6-10,
Higher Secondary = classes 11-12 (per-page headings; individual books do
not always name their exact class in the link title — class detection on
extracted content is handled separately and marked as derived).

Storage prefix for every artifact below:
    https://objectstorage.ap-dcc-gazipur-1.oraclecloud15.com/
        n/axvjbnqprylg/b/V2Ministry/o/office-nctb/2024/12/<file_id>.pdf
"""

from dataclasses import dataclass

LANDING_URL = "https://nctb.gov.bd/pages/static-pages/695b98afc4774958d7b7044c"
SECONDARY_PAGE_URL = "https://nctb.gov.bd/pages/files/6922db5b933eb65569e09a2c"
HSC_PAGE_URL = "https://nctb.gov.bd/pages/files/6922dbc6933eb65569e0c702"
STORAGE_PREFIX = (
    "https://objectstorage.ap-dcc-gazipur-1.oraclecloud15.com"
    "/n/axvjbnqprylg/b/V2Ministry/o/office-nctb/2024/12/"
)

SOURCE_PAGES = {
    "landing": LANDING_URL,
    "secondary": SECONDARY_PAGE_URL,
    "hsc": HSC_PAGE_URL,
}


@dataclass(frozen=True)
class NctbArtifact:
    """One officially linked textbook PDF."""

    file_id: str
    subject_bn: str
    level: str  # "secondary" | "hsc"
    parent_page: str
    storage_url: str

    @property
    def source_id(self) -> str:
        return f"nctb-{self.level}-{self.file_id[:12]}"

    @property
    def url(self) -> str:
        return self.storage_url


def _artifact(file_id: str, subject_bn: str, level: str, parent_page: str) -> NctbArtifact:
    return NctbArtifact(
        file_id=file_id,
        subject_bn=subject_bn,
        level=level,
        parent_page=parent_page,
        storage_url=f"{STORAGE_PREFIX}{file_id}.pdf",
    )


SECONDARY_ARTIFACTS: tuple[NctbArtifact, ...] = tuple(
    _artifact(fid, subject, "secondary", SECONDARY_PAGE_URL)
    for fid, subject in [
        ("3ce5065b7a324aee99b1a6343ae31303", "বাংলা"),
        ("afda21d8556d4dd3a2e78ec51ec72947", "ইংরেজি"),
        ("be50d8aff8d543459484e5a91a0fab38", "গণিত ও উচ্চতর গণিত"),
        ("caf9e3e659454314b4e6817203aaa61e", "কৃষি শিক্ষা"),
        ("6ce86cee9bd54d50b2146dc05dc6ef87", "চারু ও কারুকলা"),
        ("8907d1473ac04f2da68d61ac4ae9555a", "হিন্দু ধর্ম ও নৈতিক শিক্ষা"),
        ("8ad34f99d2054f8ab7669896436b8bc6", "বৌদ্ধ ধর্ম ও নৈতিক শিক্ষা"),
        ("c8b465c741804d73b888a8154cb65f7c", "ইসলাম ও নৈতিক শিক্ষা"),
        ("d911b345830346798ad4b2b1b45158d7", "খ্রিষ্টান ধর্ম ও নৈতিক শিক্ষা"),
        ("ca0d6bd886b745f1937524a89052a8b1", "আইসিটি ও ক্যারিয়ার এডুকেশন"),
        ("e39c58d357644bc4a54dd3de3b2bee7b", "বিজ্ঞান শাখার বিষয়সমূহ"),
        ("cb8f3c5aae0b452e99488875554f0028", "মানবিক শাখার বিষয়সমূহ"),
        ("bba604a37ec641d79c15a18dace2be5c", "আইসিটি (ষষ্ঠ শ্রেণি)"),
        ("fda7f4051b1e44bf80c8272dc6836e8b", "শারীরিক শিক্ষা"),
        ("11864190242f469992a5afc751cc1fcd", "ব্যবসায় শিক্ষা"),
        ("e5b3c1c1b02446b79ae42c50b197fa2a", "গার্হস্থ্যবিজ্ঞান"),
    ]
)

HSC_ARTIFACTS: tuple[NctbArtifact, ...] = tuple(
    _artifact(fid, subject, "hsc", HSC_PAGE_URL)
    for fid, subject in [
        ("753b3fc45ef74315b5bfa131f9487250", "বাংলা"),
        ("a34cc0adcff94af3a1d3d4f721a2be5c", "ইংরেজ"),
        ("9c44bb8ff649495698b093d3fe2b9f15", "উচ্চতর গণিত"),
        ("239c197cc00846d0a77f87f9d80942c4", "হিসাববিজ্ঞান"),
        ("e5c53b5f188042919706346488c4d246", "কৃষিশিক্ষা"),
        ("ca39e59575134a74b26a35b760d193eb", "জীববিজ্ঞান"),
        ("a0573d329bab479d97688d174bbbb427", "ব্যবসায় সংগঠন ও ব্যবস্থাপনা"),
        ("a513203336f643b1b2630f4980537416", "রসায়ন"),
        ("4123b86dc534431ba76c06333c12118c", "শিশুর বিকাশ"),
        ("0abcebcdcd7549fb94958664fc4c082b", "পৌরনীতি ও সুশাসন"),
        ("a590df087dd4442cbeaa15867c7886b7", "উচ্চাঙ্গ সঙ্গীত"),
        ("3c29a64f687a4e8a8ba699636ab59bdb", "অর্থনীতি"),
        ("c9be0dd8514e4c24b6a3020f72f6857b", "ফিন্যান্স, ব্যাংকিং ও বিমা"),
        ("03c10c26241f49fbb8e216b7295132fd", "খাদ্য ও পুষ্টি"),
        ("87ef3839de964c3bb73234dc3e4930d5", "ভূগোল"),
        ("4f06658e8d3b481da2802e8ec5a373f7", "ইতিহাস"),
        ("124c90f15f024ba5bc174817c7a6a308", "গৃহব্যবস্থাপনা ও পারিবারিক জীবন"),
        ("9fe6b970c94c471da7c436575fd3e488", "গার্হস্থ্যবিজ্ঞান"),
        ("687441001bc74e04819378e555a6ed8f", "তথ্য ও যোগাযোগ প্রযুক্তি"),
        ("a124bf2c89944bcca151e9c34f2fdb0f", "ইসলাম শিক্ষা"),
        ("52a05717d43b4565a6e139064dbc3e82", "ইসলামের ইতিহাস ও সংস্কৃতি"),
        ("92b3a2e42d0346acab5a3a0487786033", "লঘু সঙ্গীত"),
        ("3c6e6c526e4a47f083d56ccde2689da3", "যুক্তিবিদ্যা"),
        ("28d03c592c2c4b208f7782d04c78e01d", "পদার্থবিদ্যা"),
        ("8e3e7c4a24324a4798078138157f5e61", "শিল্পকলা ও বস্ত্রপরিচ্ছদ"),
        ("f4259fbaee554f28a360eb38aa320d00", "উৎপাদন ব্যবস্থাপনা ও বিপণন"),
        ("792b4f8b64c04b2e9b20e49b55e79c02", "মনোবিজ্ঞান"),
        ("659d5c2ef1a34e7b95b9aef58f2155a8", "সমাজকর্ম"),
        ("fcad95a8f40e4164af40928e2a4e13aa", "সমাজবিজ্ঞান"),
        ("d428c6262d754be7973bf1acf451738a", "মৃত্তিকাবিজ্ঞান"),
        ("35855aec95824c73a6afe2672255f559", "পরিসংখ্যান"),
        ("a60782747da643a7bb19c3d287638a9c", "ট্যুরিজম ও হসপিটালিটি"),
    ]
)

ALL_ARTIFACTS: tuple[NctbArtifact, ...] = SECONDARY_ARTIFACTS + HSC_ARTIFACTS


def find_artifact(file_id_prefix_or_subject: str) -> NctbArtifact | None:
    """Look up an artifact by file-id prefix or exact Bangla subject."""
    for artifact in ALL_ARTIFACTS:
        if artifact.file_id.startswith(file_id_prefix_or_subject):
            return artifact
        if artifact.subject_bn == file_id_prefix_or_subject:
            return artifact
    return None
