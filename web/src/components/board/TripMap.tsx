import type { LatLngBoundsExpression, LatLngTuple } from "leaflet";
import { useEffect, useMemo } from "react";
import { CircleMarker, MapContainer, Polyline, TileLayer, Tooltip, useMap } from "react-leaflet";
import type { BoardDay, BoardPlace } from "../../lib/api";

type Props = {
  days: BoardDay[];
  places: BoardPlace[];
  selectedPlaceId: string | null;
  onSelectPlace: (placeId: string) => void;
};

function FitToPoints({ points }: { points: LatLngTuple[] }) {
  const map = useMap();
  const key = points.map((p) => p.join(",")).join("|");
  useEffect(() => {
    if (points.length === 0) return;
    if (points.length === 1) {
      map.setView(points[0], 9);
    } else {
      map.fitBounds(points as LatLngBoundsExpression, { padding: [40, 40], maxZoom: 10 });
    }
    // Refit only when the set of points changes, not on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, key]);
  return null;
}

export default function TripMap({ days, places, selectedPlaceId, onSelectPlace }: Props) {
  const located = useMemo(
    () => places.filter((p) => p.kind === "city" && p.lat !== null && p.lng !== null),
    [places],
  );

  // Route line through base cities in the order the trip visits them.
  const route = useMemo(() => {
    const byId = new Map(located.map((p) => [p.id, p]));
    const points: LatLngTuple[] = [];
    let lastId: string | null = null;
    for (const day of days) {
      const place = day.base_place_id ? byId.get(day.base_place_id) : undefined;
      if (!place || place.id === lastId) continue;
      points.push([place.lat!, place.lng!]);
      lastId = place.id;
    }
    return points;
  }, [days, located]);

  const locating = places.some((p) => p.kind === "city" && p.locating);
  const missing = places.filter((p) => p.kind === "city" && p.lat === null && !p.locating);

  return (
    <div className="map-frame">
      <MapContainer center={[20, 0]} zoom={2} scrollWheelZoom className="map">
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <FitToPoints points={located.map((p) => [p.lat!, p.lng!] as LatLngTuple)} />
        {route.length > 1 && <Polyline positions={route} pathOptions={{ color: "#2f68a2", weight: 3, dashArray: "6 6" }} />}
        {located.map((p) => {
          const selected = p.id === selectedPlaceId;
          return (
            <CircleMarker
              key={p.id}
              center={[p.lat!, p.lng!]}
              radius={selected ? 11 : 8}
              pathOptions={{
                color: "#fff",
                weight: 2,
                fillColor: selected ? "#b54844" : "#2f68a2",
                fillOpacity: 1,
              }}
              eventHandlers={{ click: () => onSelectPlace(p.id) }}
            >
              <Tooltip direction="top" offset={[0, -8]} permanent={selected}>
                {p.name}
              </Tooltip>
            </CircleMarker>
          );
        })}
      </MapContainer>
      {(locating || missing.length > 0) && (
        <div className="map-note" role="status">
          {locating && <span>Finding your cities on the map…</span>}
          {!locating && missing.length > 0 && (
            <span>Couldn't place {missing.map((p) => p.name).join(", ")} on the map.</span>
          )}
        </div>
      )}
    </div>
  );
}
