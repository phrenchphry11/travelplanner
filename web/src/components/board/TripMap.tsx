import type { LatLngBoundsExpression, LatLngTuple } from "leaflet";
import { useEffect, useMemo } from "react";
import { CircleMarker, MapContainer, Polyline, TileLayer, Tooltip, useMap } from "react-leaflet";
import type { BoardCandidate, BoardDay, BoardLodging, BoardPlace } from "../../lib/api";

export type MapOption = { candidate: BoardCandidate; place: BoardPlace };

type Props = {
  days: BoardDay[];
  places: BoardPlace[];
  lodgings: BoardLodging[];
  chosenPlaceIds: Set<string>;
  selectedPlaceId: string | null;
  onSelectPlace: (placeId: string) => void;
  options: MapOption[]; // open drawer's options that have coordinates
  highlightedCandidateId: string | null;
  onSelectOption: (candidateId: string) => void;
  onHoverOption: (candidateId: string | null) => void;
};

const COLORS = { city: "#2f68a2", selectedCity: "#b54844", chosen: "#6d5fae", option: "#d9822b", optionHot: "#b54844", saved: "#2f9e6b" };

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

type Stop = { point: LatLngTuple; label: string; hotelPlaceId: string | null };

export default function TripMap(props: Props) {
  const { days, places, lodgings, chosenPlaceIds, selectedPlaceId, options, highlightedCandidateId } = props;

  // Where each base place "is" on the map. A chosen, pinned hotel beats the city
  // lookup, which matters for vague bases like "Central France".
  const { stops, route } = useMemo(() => {
    const byId = new Map(places.map((p) => [p.id, p]));
    const pinned = (p?: BoardPlace): p is BoardPlace => !!p && p.lat !== null && p.lng !== null;
    const stayFor = (date: string) => lodgings.find((l) => l.check_in <= date && date < l.check_out);

    const stops = new Map<string, Stop>();
    const routePoints: LatLngTuple[] = [];
    let lastKey = "";
    for (const day of days) {
      if (!day.base_place_id) continue;
      const city = byId.get(day.base_place_id);
      const hotel = byId.get(stayFor(day.date)?.place_id ?? "");
      const existing = stops.get(day.base_place_id);
      if (pinned(hotel) && (!existing || !existing.hotelPlaceId)) {
        stops.set(day.base_place_id, {
          point: [hotel.lat!, hotel.lng!],
          label: city ? `${city.name} · ${hotel.name}` : hotel.name,
          hotelPlaceId: hotel.id,
        });
      } else if (!existing && pinned(city)) {
        stops.set(day.base_place_id, { point: [city.lat!, city.lng!], label: city.name, hotelPlaceId: null });
      }
      const point: LatLngTuple | null = pinned(hotel) ? [hotel.lat!, hotel.lng!] : stops.get(day.base_place_id)?.point ?? null;
      if (!point) continue;
      const key = point.join(",");
      if (key !== lastKey) routePoints.push(point);
      lastKey = key;
    }
    return { stops, route: routePoints };
  }, [days, places, lodgings]);

  const stopHotelIds = useMemo(() => new Set([...stops.values()].map((s) => s.hotelPlaceId).filter(Boolean)), [stops]);
  const chosen = useMemo(
    () => places.filter((p) => chosenPlaceIds.has(p.id) && hasCoords(p) && !stopHotelIds.has(p.id)),
    [places, chosenPlaceIds, stopHotelIds],
  );
  const saved = useMemo(() => places.filter((p) => p.saved && hasCoords(p)), [places]);

  // With options open, zoom to them (plus the day's stop); otherwise the whole trip.
  const fitPoints: LatLngTuple[] = useMemo(() => {
    if (options.length > 0) {
      const pts = options.map((o) => [o.place.lat!, o.place.lng!] as LatLngTuple);
      const stop = selectedPlaceId ? stops.get(selectedPlaceId) : undefined;
      if (stop) pts.push(stop.point);
      return pts;
    }
    return [...stops.values()].map((s) => s.point);
  }, [options, stops, selectedPlaceId]);

  const locating = places.some((p) => p.kind === "city" && p.locating);
  const missing = places.filter((p) => p.kind === "city" && !stops.has(p.id) && !p.locating);

  return (
    <div className="map-frame">
      <MapContainer center={[20, 0]} zoom={2} scrollWheelZoom className="map">
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <FitToPoints points={fitPoints} />
        {route.length > 1 && <Polyline positions={route} pathOptions={{ color: COLORS.city, weight: 3, dashArray: "6 6" }} />}

        {[...stops.entries()].map(([placeId, stop]) => {
          const selected = placeId === selectedPlaceId;
          return (
            <CircleMarker
              key={placeId}
              center={stop.point}
              radius={selected ? 11 : 8}
              pathOptions={{ color: "#fff", weight: 2, fillColor: selected ? COLORS.selectedCity : stop.hotelPlaceId ? COLORS.chosen : COLORS.city, fillOpacity: 1 }}
              eventHandlers={{ click: () => props.onSelectPlace(placeId) }}
            >
              <Tooltip direction="top" offset={[0, -8]} permanent={selected && options.length === 0}>
                {stop.label}
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

        {saved.map((p) => (
          <CircleMarker
            key={p.id}
            center={[p.lat!, p.lng!]}
            radius={6}
            pathOptions={{ color: "#fff", weight: 2, fillColor: COLORS.saved, fillOpacity: 1 }}
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
