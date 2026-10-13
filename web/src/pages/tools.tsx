import { leaderboard, mountPage } from "../mount";
import ToolsView from "../app/ToolsView";

mountPage("tools", <ToolsView data={leaderboard} />);
