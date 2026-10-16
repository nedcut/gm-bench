import { leaderboard, mountPage } from "../mount";
import V2Archive from "../app/V2Archive";

mountPage("v2", <V2Archive data={leaderboard} />);
