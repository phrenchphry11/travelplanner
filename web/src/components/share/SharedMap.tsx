import type { LatLngBoundsExpression, LatLngTuple } from "leaflet";
import { useEffect, useMemo } from "react";
import { CircleMarker, MapContainer, Polyline, TileLayer, Tooltip, useMap } from "react-leaflet";
import { isPinned, stayForNight, type PublicPlace, type PublicTrip } from "../../lib/share";

type Props = {
  trip: PublicTrip;
  expandedDate: string | null;
  onSelectDate: (date: string) => void;
};

type Pin = { key: string; point: LatLngTuple; label: string; kind: "city" | "stay" | "plan"; dates: Set<string> };

const COLORS = { city: "#2f68a2", stay: "#6d5fae", plan: "#d9822b", active: "#b54844" };
const RADIUS = { city: 8, stay: 8, plan: 6 };

function Fit({ points }: { points: LatLngTuple[] }) {
  const map = useMap();
  const key = points.map((p) => p.join(",")).join("|");
  useEffect(() => {
    if (points.length === 0) return;
    if (points.length === 1) map.setView(points[0], 13);
    else map.fitBounds(points as LatLngBoundsExpression, { padding: [32, 32], maxZoom: 15 });
    // Refit only when the set of points changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, key]);
  return null;
}

export default function SharedMap({ trip, expandedDate, onSelectDate }: Props) {
  const { pins, route } = useMemo(() => {
    const pins = new Map<string, Pin>();
    const add = (place: PublicPlace | null | undefined, kind: Pin["kind"], date: string) => {
      if (!isPinned(place)) return;
      const key = `${kind}:${place.lat},${place.lng}:${place.name}`;
      const pin = pins.get(key) ?? { key, point: [place.lat, place.lng] as LatLngTuple, label: place.name, kind, dates: new Set<string>() };
      pin.dates.add(date);
      pins.set(key, pin);
    };
    const route: LatLngTuple[] = [];
    for (const day of trip.days) {
      const stay = stayForNight(trip, day.date);
      add(day.city, "city", day.date);
      add(stay?.place, "stay", day.date);
      day.plans.forEach((p) => add(p.place, "plan", day.date));
      // The route follows where each day is based: the night's stay if pinned, else the city.
      const base = isPinned(stay?.place) ? stay!.place : isPinned(day.city) ? day.city : null;
      if (base) {
        const point: LatLngTuple = [base.lat!, base.lng!];
        const last = route[route.length - 1];
        if (!last || last[0] !== point[0] || last[1] !== point[1]) route.push(point);
      }
    }
    return { pins: [...pins.values()], route };
  }, [trip]);

  const fitPoints = useMemo(() => {
    const active = expandedDate ? pins.filter((p) => p.dates.has(expandedDate)) : [];
    const chosen = active.length > 0 ? active : pins.filter((p) => p.kind !== "plan");
    return (chosen.length > 0 ? chosen : pins).map((p) => p.point);
  }, [pins, expandedDate]);

  // Draw the active day's pins last so they sit on top.
  const ordered = [...pins].sort((a, b) => Number(!!expandedDate && a.dates.has(expandedDate)) - Number(!!expandedDate && b.dates.has(expandedDate)));

  return (
    <div className="shared-map">
      <MapContainer center={[20, 0]} zoom={2} scrollWheelZoom={false} className="map">
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <Fit points={fitPoints} />
        {route.length > 1 && <Polyline positions={route} pathOptions={{ color: COLORS.city, weight: 3, dashArray: "6 6" }} />}
        {ordered.map((pin) => {
          const active = !!expandedDate && pin.dates.has(expandedDate);
          const firstDate = [...pin.dates].sort()[0];
          return (
            <CircleMarker
              key={pin.key}
              center={pin.point}
              radius={RADIUS[pin.kind] + (active ? 3 : 0)}
              pathOptions={{ color: "#fff", weight: 2, fillColor: active ? COLORS.active : COLORS[pin.kind], fillOpacity: expandedDate && !active ? 0.6 : 1 }}
              eventHandlers={{ click: () => onSelectDate(expandedDate && pin.dates.has(expandedDate) ? expandedDate : firstDate) }}
            >
              <Tooltip direction="top" offset={[0, -6]}>{pin.label}</Tooltip>
            </CircleMarker>
          );
        })}
      </MapContainer>
      {pins.length === 0 && <div className="map-note">Nothing on the map yet.</div>}
    </div>
  );
}
