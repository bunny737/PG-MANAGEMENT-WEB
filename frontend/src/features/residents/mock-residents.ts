export interface Resident {
  id: string;
  name: string;
  unit: string;
  block: string;
  floor: number;
  status: "active" | "notice_period" | "inactive";
  moveInDate: string;
  phone: string;
  email: string;
}

export const mockResidents: Resident[] = [
  {
    id: "8492",
    name: "Eleanor Shellstrop",
    unit: "A-101",
    block: "A",
    floor: 1,
    status: "active",
    moveInDate: "Jan 2024",
    phone: "+1 (555) 019-2834",
    email: "eleanor.s@example.com",
  },
  {
    id: "1",
    name: "Alex Johnson",
    unit: "A-302",
    block: "A",
    floor: 3,
    status: "active",
    moveInDate: "Oct 2022",
    phone: "+91 98765 43210",
    email: "alex.j@example.com",
  },
  {
    id: "2",
    name: "Sarah Miller",
    unit: "B-105",
    block: "B",
    floor: 1,
    status: "notice_period",
    moveInDate: "Jan 2023",
    phone: "+91 87654 32109",
    email: "sarah.m@example.com",
  },
  {
    id: "3",
    name: "David Park",
    unit: "A-412",
    block: "A",
    floor: 4,
    status: "active",
    moveInDate: "Mar 2021",
    phone: "+91 76543 21098",
    email: "david.p@example.com",
  },
  {
    id: "4",
    name: "Rohan Sharma",
    unit: "C-204",
    block: "C",
    floor: 2,
    status: "active",
    moveInDate: "Dec 2024",
    phone: "+91 98989 89898",
    email: "rohan.s@example.com",
  },
  {
    id: "5",
    name: "Priya Patel",
    unit: "B-302",
    block: "B",
    floor: 3,
    status: "notice_period",
    moveInDate: "Jul 2023",
    phone: "+91 99999 88888",
    email: "priya.p@example.com",
  },
  {
    id: "6",
    name: "Vikram Rao",
    unit: "A-101",
    block: "A",
    floor: 1,
    status: "inactive",
    moveInDate: "Feb 2020",
    phone: "+91 91111 22222",
    email: "vikram.r@example.com",
  },
];
