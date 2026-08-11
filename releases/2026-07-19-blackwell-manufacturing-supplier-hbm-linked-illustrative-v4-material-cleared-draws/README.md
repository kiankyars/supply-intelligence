# Blackwell manufacturing with supplier HBM draws and material-cleared package starts

Quarter: `2026-Q3`. As of: `2026-07-19`. Draws: `20,000`.

**This linked manufacturing run remains illustrative. Logic, packaging, supplier HBM capacity, yields, qualification, allocation, and demand contain synthetic inputs. It is not an estimate of actual Blackwell production.**

Open `dashboard.html` first. The aggregate HBM wafer branch is removed and replaced once by customer-allocated stacks from the hash-pinned supplier result. `link_lineage.json` records the removed flow, source hashes, topology checks, and the deterministic draw permutation. Both source documents, the exact capacity draws, and the link recipe are preserved byte for byte.
 Package assembly starts are explicitly declared material-cleared for silicon_interposer, abf_substrate; this synthetic scope prevents those pools from being linked a second time.
