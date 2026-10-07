"""
Call of Duty League Stats Aggregator
Handles stat calculation, averages, K/D ratios, and MVP determination.
"""
from typing import List, Dict, Any, Optional
from collections import defaultdict


class StatsManager:
    """Manages player statistics across multiple maps/games in a series."""

    @staticmethod
    def calculate_kd(kills: int, deaths: int) -> float:
        """Calculate K/D ratio, handling 0 deaths gracefully."""
        if deaths == 0:
            return float(kills)
        return round(kills / deaths, 2)

    @staticmethod
    def calculate_differential(kills: int, deaths: int) -> int:
        """Calculate +/- kill differential."""
        return kills - deaths

    @classmethod
    def aggregate_series_stats(cls, maps_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Aggregates player statistics across all maps in a series.
        
        Input: list of map dictionaries:
        [
            {
                "map_number": 1,
                "map_name": "Skyline",
                "game_mode": "Hardpoint",
                "team1_name": "OpTic",
                "team2_name": "FaZe",
                "team1_score": 250,
                "team2_score": 210,
                "players": [
                    {
                        "name": "Shotzzy",
                        "team": "OpTic",
                        "kills": 32,
                        "deaths": 24,
                        "assists": 8,
                        "damage": 4350,
                        "score": 3800,
                        "objective": "1:24"
                    },
                    ...
                ]
            }
        ]
        """
        if not maps_data:
            return {
                "total_maps": 0,
                "teams": {},
                "players": [],
                "mvp": None,
                "team_scores": {},
                "maps_summary": []
            }

        player_totals = defaultdict(lambda: {
            "name": "",
            "team": "Unknown",
            "maps_played": 0,
            "kills": 0,
            "deaths": 0,
            "assists": 0,
            "damage": 0,
            "score": 0,
            "map_records": []  # List of {map_num, map_name, kills, deaths, kd, damage}
        })

        team_wins = defaultdict(int)
        team_total_scores = defaultdict(int)

        maps_summary = []

        for m_idx, map_info in enumerate(maps_data, start=1):
            map_num = map_info.get("map_number", m_idx)
            map_name = map_info.get("map_name", f"Map {map_num}")
            game_mode = map_info.get("game_mode", "Multiplayer")
            t1_name = map_info.get("team1_name", "Team 1")
            t2_name = map_info.get("team2_name", "Team 2")
            t1_score = map_info.get("team1_score", 0)
            t2_score = map_info.get("team2_score", 0)

            team_total_scores[t1_name] += t1_score
            team_total_scores[t2_name] += t2_score

            if t1_score > t2_score:
                team_wins[t1_name] += 1
                winner = t1_name
            elif t2_score > t1_score:
                team_wins[t2_name] += 1
                winner = t2_name
            else:
                winner = "Tie"

            maps_summary.append({
                "map_number": map_num,
                "map_name": map_name,
                "game_mode": game_mode,
                "team1_name": t1_name,
                "team1_score": t1_score,
                "team2_name": t2_name,
                "team2_score": t2_score,
                "winner": winner
            })

            # Process players
            for p in map_info.get("players", []):
                pname = p.get("name", "").strip()
                if not pname:
                    continue

                # Standardize player key to handle case-insensitivity
                pkey = pname.lower()
                rec = player_totals[pkey]
                rec["name"] = pname  # Keep formatted name
                if p.get("team"):
                    rec["team"] = p.get("team")
                
                pkills = int(p.get("kills", 0) or 0)
                pdeaths = int(p.get("deaths", 0) or 0)
                passists = int(p.get("assists", 0) or 0)
                pdamage = int(p.get("damage", 0) or 0)
                pscore = int(p.get("score", 0) or 0)

                rec["maps_played"] += 1
                rec["kills"] += pkills
                rec["deaths"] += pdeaths
                rec["assists"] += passists
                rec["damage"] += pdamage
                rec["score"] += pscore

                rec["map_records"].append({
                    "map_number": map_num,
                    "map_name": map_name,
                    "game_mode": game_mode,
                    "kills": pkills,
                    "deaths": pdeaths,
                    "kd": cls.calculate_kd(pkills, pdeaths),
                    "plus_minus": cls.calculate_differential(pkills, pdeaths),
                    "assists": passists,
                    "damage": pdamage,
                    "score": pscore,
                    "objective": p.get("objective", "")
                })

        # Calculate final aggregated stats and averages for each player
        aggregated_players = []
        for pkey, stats in player_totals.items():
            maps_cnt = max(stats["maps_played"], 1)
            total_k = stats["kills"]
            total_d = stats["deaths"]
            total_dmg = stats["damage"]
            total_score = stats["score"]
            total_ast = stats["assists"]

            kd = cls.calculate_kd(total_k, total_d)
            diff = cls.calculate_differential(total_k, total_d)
            avg_k = round(total_k / maps_cnt, 1)
            avg_d = round(total_d / maps_cnt, 1)
            avg_dmg = round(total_dmg / maps_cnt, 1)
            avg_ast = round(total_ast / maps_cnt, 1)
            avg_score = round(total_score / maps_cnt, 1)

            # Rating score for MVP calculation:
            # Heavily rewards K/D, Kills/map, and Damage/map
            mvp_rating = round((kd * 35.0) + (avg_k * 2.0) + (avg_dmg * 0.01) + (diff * 1.5), 1)

            player_summary = {
                "name": stats["name"],
                "team": stats["team"],
                "maps_played": stats["maps_played"],
                "kills": total_k,
                "deaths": total_d,
                "assists": total_ast,
                "damage": total_dmg,
                "score": total_score,
                "plus_minus": diff,
                "kd": kd,
                "avg_kills": avg_k,
                "avg_deaths": avg_d,
                "avg_assists": avg_ast,
                "avg_damage": avg_dmg,
                "avg_score": avg_score,
                "mvp_rating": mvp_rating,
                "map_records": stats["map_records"]
            }
            aggregated_players.append(player_summary)

        # Sort players primarily by MVP rating (or K/D)
        aggregated_players.sort(key=lambda x: (x["mvp_rating"], x["kd"], x["kills"]), reverse=True)

        # Identify MVP
        mvp = aggregated_players[0] if aggregated_players else None

        # Top performers
        top_kills = max(aggregated_players, key=lambda x: x["kills"]) if aggregated_players else None
        top_damage = max(aggregated_players, key=lambda x: x["damage"]) if aggregated_players else None
        top_kd = max(aggregated_players, key=lambda x: x["kd"]) if aggregated_players else None

        return {
            "total_maps": len(maps_data),
            "maps_summary": maps_summary,
            "team_wins": dict(team_wins),
            "team_total_scores": dict(team_total_scores),
            "players": aggregated_players,
            "mvp": mvp,
            "top_kills": top_kills,
            "top_damage": top_damage,
            "top_kd": top_kd
        }
