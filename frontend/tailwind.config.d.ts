declare const _default: {
    content: string[];
    theme: {
        extend: {
            colors: {
                ink: string;
                mist: string;
                line: string;
                glow: string;
                teal: string;
                sand: string;
                gold: string;
            };
            boxShadow: {
                soft: string;
                lift: string;
            };
            backgroundImage: {
                "hero-grid": string;
            };
            animation: {
                floaty: string;
                shimmer: string;
                rise: string;
            };
            keyframes: {
                floaty: {
                    "0%, 100%": {
                        transform: string;
                    };
                    "50%": {
                        transform: string;
                    };
                };
                shimmer: {
                    "0%, 100%": {
                        opacity: string;
                    };
                    "50%": {
                        opacity: string;
                    };
                };
                rise: {
                    from: {
                        opacity: string;
                        transform: string;
                    };
                    to: {
                        opacity: string;
                        transform: string;
                    };
                };
            };
        };
    };
    plugins: any[];
};
export default _default;
