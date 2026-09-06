"""
Maps API fixture responses for unit tests.

THIS IS TEST FIXTURE DATA — NOT REAL GOOGLE MAPS API RESPONSES.
These are representative response structures matching the Maps Routes API v2
JSON schema, used to test parsing logic without live API calls.
"""

from typing import Dict, Any


def get_drive_route_fixture() -> Dict[str, Any]:
    """Single DRIVE route with traffic data (traffic adds ~8 min delay)."""
    return {
        "routes": [
            {
                "duration": "2280s",          # 38 min with traffic
                "staticDuration": "1800s",    # 30 min without traffic
                "distanceMeters": 18500,
                "description": "via NH 44",
                "legs": [
                    {
                        "duration": "2280s",
                        "distanceMeters": 18500,
                        "stepsOverview": {}
                    }
                ]
            }
        ]
    }


def get_drive_alternative_routes_fixture() -> Dict[str, Any]:
    """Two DRIVE routes (main + alternative)."""
    return {
        "routes": [
            {
                "duration": "2280s",
                "staticDuration": "1800s",
                "distanceMeters": 18500,
                "description": "via NH 44",
                "legs": [{"duration": "2280s", "distanceMeters": 18500}]
            },
            {
                "duration": "2580s",
                "staticDuration": "2100s",
                "distanceMeters": 21000,
                "description": "via Hosur Road",
                "legs": [{"duration": "2580s", "distanceMeters": 21000}]
            }
        ]
    }


def get_transit_route_fixture() -> Dict[str, Any]:
    """TRANSIT route with one metro leg and walking segments."""
    return {
        "routes": [
            {
                "duration": "3300s",         # 55 min total
                "staticDuration": "3300s",
                "distanceMeters": 22000,
                "description": "via BMTC + Namma Metro",
                "legs": [
                    {
                        "duration": "3300s",
                        "distanceMeters": 22000,
                        "steps": [
                            {
                                "travelMode": "WALK",
                                "staticDuration": "300s",    # 5 min walk
                                "distanceMeters": 400,
                                "navigationInstruction": {"instructions": "Walk to bus stop"}
                            },
                            {
                                "travelMode": "TRANSIT",
                                "staticDuration": "1800s",   # 30 min bus
                                "distanceMeters": 15000,
                                "transitDetails": {
                                    "stopDetails": {},
                                    "headsign": "Koramangala"
                                }
                            },
                            {
                                "travelMode": "WALK",
                                "staticDuration": "420s",    # 7 min walk
                                "distanceMeters": 550,
                                "navigationInstruction": {"instructions": "Walk to metro"}
                            },
                            {
                                "travelMode": "TRANSIT",
                                "staticDuration": "600s",    # 10 min metro
                                "distanceMeters": 6000,
                                "transitDetails": {
                                    "stopDetails": {},
                                    "headsign": "MG Road"
                                }
                            },
                            {
                                "travelMode": "WALK",
                                "staticDuration": "180s",   # 3 min walk
                                "distanceMeters": 250,
                                "navigationInstruction": {"instructions": "Walk to destination"}
                            }
                        ]
                    }
                ]
            }
        ]
    }


def get_walk_route_fixture() -> Dict[str, Any]:
    """Short WALK route."""
    return {
        "routes": [
            {
                "duration": "900s",          # 15 min walk
                "staticDuration": "900s",
                "distanceMeters": 1200,
                "description": "Walk via 12th Main Rd",
                "legs": [
                    {
                        "duration": "900s",
                        "distanceMeters": 1200
                    }
                ]
            }
        ]
    }


def get_empty_routes_fixture() -> Dict[str, Any]:
    """API response with no routes (e.g., incompatible origin/destination for mode)."""
    return {"routes": []}


def get_no_routes_key_fixture() -> Dict[str, Any]:
    """API response missing the routes key entirely."""
    return {}
