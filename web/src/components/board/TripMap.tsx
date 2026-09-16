import type { LatLngBoundsExpression, LatLngTuple } from "leaflet";
import { useEffect, useMemo } from "react";
import { CircleMarker, MapContainer, Polyline, TileLayer, Tooltip, useMap } from "react-leaflet";
import type { BoardCandidate, BoardDay, BoardPlace } from "../../lib/api";

export type MapOption = { candidate: BoardCandidate; place: BoardPlace };

type Props = {
  days: BoardDay[];
  places: BoardPlace[];
  chosenPlaceIds: Set<string>;
  selectedPlaceId: string | null;
  onSelectPlace: (placeId: string) => void;
  options: MapOption[]; // open drawer's options that have coordinates
  highlightedCandidateId: string | null;
  onSelectOption: (candidateId: string) => void;
  onHoverOption: (candidateId: string | null) => void;
};

const COLORS = { city: "#2f68a2", selectedCity: "#b54844", chosen: "#6d5fae", option: "#d9822b", optionHot: "#b54844" };

function FitToPoints({ points }: { points: LatLngTuple[] }) {
  const map = useMap();
  const key = points.map((p) => p.join(",")).join("|");
  useEffect(() => {
    if (points.length === 0) return;
    if (points.length === 1) {
      map.setView(points[0], 13);
    } else {
      map.fitBounds(points as LatLngBoundsExpression, { padding: [40, 40], maxZoom: 15 });
    }
    // Refit only when the set of points changes, not on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, key]);
  return null;
}

const hasCoords = (p: BoardPlace) => p.lat !== null && p.lng !== null;

export default function TripMap(props: Props) {
  const { days, places, chosenPlaceIds, selectedPlaceId, options, highlightedCandidateId } = props;
  const cities = useMemo(() => places.filter((p) => p.kind === "city" && hasCoords(p)), [places]);
  const chosen = useMemo(() => places.filter((p) => chosenPlaceIds.has(p.id) && hasCoords(p)), [places, chosenPlaceIds]);

  const route = useMemo(() => {
    const byId = new Map(cities.map((p) => [p.id, p]));
    const points: LatLngTuple[] = [];
    let lastId: string | null = null;
    for (const day of days) {
      const place = day.base_place_id ? byId.get(day.base_place_id) : undefined;
      if (!place || place.id === lastId) continue;
      points.push([place.lat!, place.lng!]);
      lastId = place.id;
    }
    return points;
  }, [days, cities]);

  // With options open, zoom to them (plus the day's city); otherwise the whole trip.
  const fitPoints: LatLngTuple[] = useMemo(() => {
    if (options.length > 0) {
      const pts = options.map((o) => [o.place.lat!, o.place.lng!] as LatLngTuple);
      const city = cities.find((c) => c.id === selectedPlaceId);
      if (city) pts.push([city.lat!, city.lng!]);
      return pts;
    }
    return cities.map((p) => [p.lat!, p.lng!] as LatLngTuple);
  }, [options, cities, selectedPlaceId]);

  const locating = places.some((p) => p.kind === "city" && p.locating);
  const missing = places.filter((p) => p.kind === "city" && p.lat === null && !p.locating);

  return (
    <div className="map-frame">
      <MapContainer center={[20, 0]} zoom={2} scrollWheelZoom className="map">
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <FitToPoints points={fitPoints} />
        {route.length > 1 && <Polyline positions={route} pathOptions={{ color: COLORS.city, weight: 3, dashArray: "6 6" }} />}

        {cities.map((p) => {
          const selected = p.id === selectedPlaceId;
          return (
            <CircleMarker
              key={p.id}
              center={[p.lat!, p.lng!]}
              radius={selected ? 11 : 8}
              pathOptions={{ color: "#fff", weight: 2, fillColor: selected ? COLORS.selectedCity : COLORS.city, fillOpacity: 1 }}
              eventHandlers={{ click: () => props.onSelectPlace(p.id) }}
            >
              <Tooltip direction="top" offset={[0, -8]} permanent={selected && options.length === 0}>
                {p.name}
              </Tooltip>
            </CircleMarker>
          );
        })}

        {chosen.map((p) => (
          <CircleMarker
            key={p.id}
            center={[p.lat!, p.lng!]}
            radius={7}
            pathOptions={{ color: "#fff", weight: 2, fillColor: COLORS.chosen, fillOpacity: 1 }}
          >
            <Tooltip direction="top" offset={[0, -6]}>{p.name}</Tooltip>
          </CircleMarker>
        ))}

        {options.map(({ candidate, place }) => {
          const hot = candidate.id === highlightedCandidateId;
          return (
            <CircleMarker
              key={candidate.id}
              center={[place.lat!, place.lng!]}
              radius={hot ? 12 : 8}
              pathOptions={{ color: "#fff", weight: 2, fillColor: hot ? COLORS.optionHot : COLORS.option, fillOpacity: 1 }}
              eventHandlers={{
                click: () => props.onSelectOption(candidate.id),
                mouseover: () => props.onHoverOption(candidate.id),
                mouseout: () => props.onHoverOption(null),
              }}
            >
              <Tooltip direction="top" offset={[0, -8]} permanent={hot}>{candidate.name}</Tooltip>
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
