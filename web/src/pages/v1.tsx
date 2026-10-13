import { leaderboard, mountPage } from "../mount";
import V1Archive from "../app/V1Archive";

mountPage("v1", <V1Archive data={leaderboard} />);
