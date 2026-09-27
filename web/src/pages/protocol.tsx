import snapshotData from "../data/snapshot.json";
import type { Snapshot } from "../types";
import { mountPage } from "../mount";
import PageHeader from "../components/PageHeader";
import HowItWorks from "../components/HowItWorks";
import Quickstart from "../components/Quickstart";

mountPage(
  "protocol",
  <>
    <PageHeader
      kicker="The rules"
      title="How a season works."
      jumps={[
        { href: "#protocol", label: "The protocol" },
        { href: "#quickstart", label: "Run it" },
      ]}
    >
      <p>
        The agent reads one JSON observation per decision and writes one JSON batch of actions
        back. Any process that can do that can play, and the same seed always produces the same
        league.
      </p>
    </PageHeader>
    <HowItWorks snapshot={snapshotData as Snapshot} />
    <Quickstart />
  </>,
);
