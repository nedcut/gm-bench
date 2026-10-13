import { leaderboard, mountPage } from "../mount";
import HowItWorks from "../app/HowItWorks";

mountPage("how", <HowItWorks data={leaderboard} />);
