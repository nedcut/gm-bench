import { leaderboard, mountPage } from "../mount";
import Method from "../app/Method";

mountPage("method", <Method data={leaderboard} />);
