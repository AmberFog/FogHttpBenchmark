__all__ = ("FOGHTTP_BASELINE", "ResearchBaseline")

from dataclasses import dataclass


@dataclass(frozen=True)
class ResearchBaseline:
    repository: str
    ref: str
    sha: str
    version: str
    rust_version: str
    maturin_version: str
    setuptools_version: str
    wheel_version: str

    @property
    def branch(self) -> str:
        return self.ref.removeprefix("refs/heads/")

    @property
    def tracking_ref(self) -> str:
        return f"refs/remotes/origin/{self.branch}"

    @property
    def build_requirements(self) -> tuple[str, ...]:
        return (
            f"maturin=={self.maturin_version}",
            f"setuptools=={self.setuptools_version}",
            f"wheel=={self.wheel_version}",
        )


FOGHTTP_BASELINE = ResearchBaseline(
    repository="https://github.com/AmberFog/foghttp.git",
    ref="refs/heads/release/0.4.2",
    sha="51a25f232d3ef39869f1f182596ac64d7aab11f6",  # pragma: allowlist secret - public Git commit
    version="0.4.2",
    rust_version="1.95.0",
    maturin_version="1.14.1",
    setuptools_version="80.9.0",
    wheel_version="0.45.1",
)
