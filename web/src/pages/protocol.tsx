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
      kicker="Rules"
      title="How a season works"
      jumps={[
        { href: "#protocol", label: "The protocol" },
        { href: "#quickstart", label: "Run it" },
      ]}
    >
      <p>Any program that reads JSON and writes JSON can play. The same seed always builds the same league.</p>
    </PageHeader>
    <HowItWorks snapshot={snapshotData as Snapshot} />
    <Quickstart />
  </>,
);
