import { leaderboard, mountPage } from "../mount";
import CostView from "../app/CostView";

mountPage("cost", <CostView data={leaderboard} />);
