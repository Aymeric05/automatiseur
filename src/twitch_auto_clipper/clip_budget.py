"""Configurable clip-count policy for discovered Twitch live streams."""

from dataclasses import dataclass

from .twitch_api import LiveStream


@dataclass(frozen=True)
class ClipBudgetTier:
    minimum_viewers: int
    clip_count: int


@dataclass(frozen=True)
class ClipBudgetPolicy:
    """Viewer thresholds and corresponding clip counts, highest first."""

    tiers: tuple[ClipBudgetTier, ...]

    def __post_init__(self) -> None:
        if not self.tiers or self.tiers[-1].minimum_viewers != 0:
            raise ValueError("the policy must include a zero-viewer threshold")
        previous_minimum: int | None = None
        for tier in self.tiers:
            if tier.minimum_viewers < 0 or tier.clip_count < 0:
                raise ValueError("viewer thresholds and clip counts must be non-negative")
            if previous_minimum is not None and tier.minimum_viewers >= previous_minimum:
                raise ValueError("viewer thresholds must be strictly descending")
            previous_minimum = tier.minimum_viewers

    @property
    def minimum_eligible_viewers(self) -> int | None:
        """Lowest viewer count that earns at least one clip (None if none do)."""
        eligible = [tier.minimum_viewers for tier in self.tiers if tier.clip_count > 0]
        return min(eligible) if eligible else None

    def clips_for_viewers(self, viewer_count: int) -> int:
        if viewer_count < 0:
            raise ValueError("viewer_count must be non-negative")
        for tier in self.tiers:
            if viewer_count >= tier.minimum_viewers:
                return tier.clip_count
        raise AssertionError("validated policy must include a zero-viewer threshold")


DEFAULT_CLIP_BUDGET_POLICY = ClipBudgetPolicy(
    tiers=(
        ClipBudgetTier(minimum_viewers=100_000, clip_count=20),
        ClipBudgetTier(minimum_viewers=50_000, clip_count=15),
        ClipBudgetTier(minimum_viewers=20_000, clip_count=10),
        ClipBudgetTier(minimum_viewers=10_000, clip_count=5),
        ClipBudgetTier(minimum_viewers=5_000, clip_count=2),
        ClipBudgetTier(minimum_viewers=0, clip_count=0),
    )
)


def clip_count_for_stream(
    stream: LiveStream,
    policy: ClipBudgetPolicy = DEFAULT_CLIP_BUDGET_POLICY,
) -> int:
    """Return the configured clip budget for a discovered live stream."""
    return policy.clips_for_viewers(stream.viewer_count)