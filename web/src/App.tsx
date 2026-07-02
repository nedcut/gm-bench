import snapshotData from "./data/snapshot.json";
import type { Snapshot } from "./types";
import Nav from "./components/Nav";
import Hero from "./components/Hero";
import Results from "./components/Results";
import HowItWorks from "./components/HowItWorks";
import Adapters from "./components/Adapters";
import Quickstart from "./components/Quickstart";
import Footer from "./components/Footer";

const snapshot = snapshotData as Snapshot;

export default function App() {
  return (
    <>
      <Nav />
      <main>
        <Hero snapshot={snapshot} />
        <Results snapshot={snapshot} />
        <HowItWorks snapshot={snapshot} />
        <Adapters />
        <Quickstart />
      </main>
      <Footer snapshot={snapshot} />
    </>
  );
}
