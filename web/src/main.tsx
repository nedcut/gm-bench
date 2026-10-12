import { leaderboard, mountPage } from "./mount";
import Standings from "./app/Standings";

mountPage("standings", <Standings data={leaderboard} />);
