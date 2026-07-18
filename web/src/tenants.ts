// The advisory firms the API serves (D-028). Ids match the tenant path
// segments; display names are the fictional firm names the brief established.
export interface Tenant {
    id: string;
    name: string;
    tagline: string;
}

export const TENANTS: Tenant[] = [
    {
        id: "aldergate",
        name: "Aldergate Wealth Management",
        tagline: "Private wealth advisory",
    },
    {
        id: "stonefield",
        name: "Stonefield Family Office",
        tagline: "Multi-family office",
    },
];
