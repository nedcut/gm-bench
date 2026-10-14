import { leaderboard, mountPage } from "./mount";
import Stats from "./app/Stats";

mountPage("standings", <Stats data={leaderboard} />);
